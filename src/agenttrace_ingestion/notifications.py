"""Validate metadata-only Graph notifications before a durable inbox transaction."""

from __future__ import annotations

import hmac
import json
import re
from typing import Any
from urllib.parse import unquote

from .contracts import Enrollment, IngestionError, SourceNotification, utc_now
from .mailbox import instant
from .protection import EvidenceCipher


class NotificationValidator:
    def __init__(self, enrollment: Enrollment, cipher: EvidenceCipher, subscription_ids: set[str]):
        self.enrollment, self.cipher, self.subscription_ids = enrollment, cipher, subscription_ids

    def parse(self, raw: bytes, *, cloud_events: bool = False) -> list[SourceNotification]:
        if len(raw) > 65_536:
            raise IngestionError("notification_size_limit")
        try:
            payload = json.loads(raw)
            items = payload if cloud_events else payload["value"]
            if cloud_events and isinstance(items, dict):
                items = [items]
            if not isinstance(items, list) or not 1 <= len(items) <= 100:
                raise ValueError
            return [self._item(item, cloud_events) for item in items]
        except IngestionError:
            raise
        except (ValueError, KeyError, TypeError, AttributeError):
            raise IngestionError("notification_shape_invalid") from None

    def _item(self, item: dict[str, Any], cloud: bool) -> SourceNotification:
        now = utc_now()
        data = item["data"] if cloud else item
        if cloud:
            data = dict(data)
            # Outlook's Event Grid envelope uses PascalCase for these fields,
            # while basic Graph notifications use camelCase. Accept only these
            # explicit aliases and reject conflicting duplicate representations.
            for upstream, canonical in {
                "SubscriptionId": "subscriptionId",
                "ChangeType": "changeType",
                "Resource": "resource",
                "ResourceData": "resourceData",
                "LifecycleEvent": "lifecycleEvent",
            }.items():
                if upstream in data:
                    if canonical in data:
                        raise IngestionError("notification_field_alias_conflict")
                    data[canonical] = data.pop(upstream)
        tenant = str(self.enrollment.tenant_id)
        if cloud and (
            item.get("specversion") != "1.0"
            or item.get("source", "").lower()
            != f"/tenants/{tenant}/applications/{self.enrollment.collector_client_id}".lower()
        ):
            raise IngestionError("notification_cloud_source_invalid")
        if str(data.get("tenantId", "")).lower() != tenant.lower():
            raise IngestionError("notification_tenant_invalid")
        if not hmac.compare_digest(
            str(data.get("clientState", "")), self.enrollment.client_state.get_secret_value()
        ):
            raise IngestionError("notification_client_state_invalid")
        subscription = str(data["subscriptionId"])
        if subscription not in self.subscription_ids:
            raise IngestionError("notification_subscription_invalid")
        change = data.get("lifecycleEvent") or data.get("changeType") or data.get("ChangeType")
        if cloud and not change:
            lifecycle = str(item.get("type", "")).split(".")[-1]
            change = {
                "subscriptionReauthorizationRequired": "reauthorizationRequired",
                "subscriptionRemoved": "subscriptionRemoved",
                "missed": "missed",
            }.get(lifecycle)
        if change not in {
            "created",
            "updated",
            "deleted",
            "missed",
            "subscriptionRemoved",
            "reauthorizationRequired",
        }:
            raise IngestionError("notification_change_invalid")
        message_id = None
        resource = str(data.get("resource", ""))
        if change in {"created", "updated", "deleted"}:
            # Match structure before decoding IDs: IDs are opaque and case-sensitive.
            match = re.fullmatch(r"/?[Uu]sers/([^/]+)/[Mm]essages/([^/]+)", resource)
            if (
                match is None
                or unquote(match[1]).lower() != str(self.enrollment.mailbox_id).lower()
            ):
                raise IngestionError("notification_mailbox_invalid")
            message_id = unquote(match[2])
            resource_data = data.get("resourceData") or {}
            if set(resource_data) - {"id", "Id", "@odata.type", "@odata.id", "@odata.etag"}:
                raise IngestionError("rich_notifications_not_supported")
            if resource_data.get("id", resource_data.get("Id", message_id)) != message_id:
                raise IngestionError("notification_identifier_conflict")
        event_time = instant(item["time"]) if cloud and item.get("time") else None
        # Basic Graph notifications have no event ID. Identical metadata can coalesce;
        # each accepted event reads the current version and delta recovers final state.
        event_key = (
            str(item.get("id"))
            if cloud
            else json.dumps(
                {
                    "subscription": subscription,
                    "resource": resource,
                    "change": change,
                    "etag": (data.get("resourceData") or {}).get("@odata.etag"),
                    "minute": now.isoformat()[:16],
                },
                sort_keys=True,
            )
        )
        return SourceNotification(
            source_ref=self.enrollment.source_ref,
            event_ref=self.cipher.reference(
                str(self.enrollment.source_ref), "notification:" + event_key
            ),
            subscription_ref=subscription,
            message_id=message_id,
            change=change,
            event_time=event_time,
            received_at=now,
        )
