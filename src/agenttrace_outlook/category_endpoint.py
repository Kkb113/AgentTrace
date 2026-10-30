"""Fixed-mailbox, categories-only conditional updates on inspected synthetic items."""

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from agenttrace_ingestion.contracts import IngestionError

from .category_contracts import CategoryOwnership, CategorySettings, Label
from .category_ownership import normalized_name
from .category_write_contracts import CategoryEndpointQualification
from .errors import OutlookError

FIELDS = (
    "id,changeKey,parentFolderId,receivedDateTime,sentDateTime,isDraft,isRead,subject,"
    "internetMessageId,internetMessageHeaders,categories"
)


class CategoryEndpoint:
    def __init__(self, settings: CategorySettings, transport: Any):
        self.settings, self.transport = settings, transport
        self.base = "https://graph.microsoft.com/v1.0/users/" + str(settings.scope.mailbox_id)

    def url(self, message_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:/+=-]{1,2048}", message_id):
            raise OutlookError("category_message_reference_invalid")
        return self.base + "/messages/" + quote(message_id, safe="")

    def read(self, message_id: str) -> dict[str, Any]:
        row: dict[str, Any] = self.transport.request(
            "GET",
            self.url(message_id) + "?$select=" + FIELDS,
            headers={"Prefer": 'IdType="ImmutableId"'},
        )
        if (
            row.get("id") != message_id
            or row.get("isDraft") is not False
            or type(row.get("isRead")) is not bool
            or not isinstance(row.get("subject"), str)
            or not row["subject"].startswith("AgentTrace synthetic test:")
            or not isinstance(row.get("parentFolderId"), str)
            or not isinstance(row.get("changeKey"), str)
            or not re.fullmatch(
                r'(?:W/)?"[A-Za-z0-9+/=_-]{1,512}"', str(row.get("@odata.etag", ""))
            )
            or not isinstance(row.get("categories"), list)
            or len(row["categories"]) > 100
            or any(
                not isinstance(c, str) or not 1 <= len(c) <= 255 or any(ord(x) < 32 for x in c)
                for c in row["categories"]
            )
            or len(set(row["categories"])) != len(row["categories"])
        ):
            raise OutlookError("category_current_message_invalid_or_not_synthetic")
        return row

    @staticmethod
    def merged(current: list[str], registry: CategoryOwnership, label: Label | None) -> list[str]:
        managed = {c.category.display_name for c in registry.categories}
        if any(
            c not in managed and normalized_name(c) in {normalized_name(n) for n in managed}
            for c in current
        ):
            raise OutlookError("category_item_name_ambiguous")
        result = [c for c in current if c not in managed]
        return result + ([label] if label is not None else [])

    def write(
        self, before: dict[str, Any], registry: CategoryOwnership, label: Label | None
    ) -> dict[str, Any]:
        if (
            registry.scope != self.settings.scope
            or registry.writer_client_id != self.settings.writer_identity.client_id
        ):
            raise OutlookError("category_write_registry_scope_mismatch")
        return self._patch(before, self.merged(before["categories"], registry, label))

    def _patch(self, before: dict[str, Any], categories: list[str]) -> dict[str, Any]:
        # Internal worker supplies a journaled merge; no caller-selectable route or properties.
        result: dict[str, Any] = self.transport.request(
            "PATCH",
            self.url(before["id"]) + "?$select=id,changeKey,categories",
            body={"categories": categories},
            headers={"Prefer": 'IdType="ImmutableId"', "If-Match": before["@odata.etag"]},
        )
        return result

    def qualify(self, message_id: str, now: datetime) -> CategoryEndpointQualification:
        before = self.read(message_id)
        self._patch(before, before["categories"])
        after = self.read(message_id)
        if (
            before["categories"] != after["categories"]
            or before["@odata.etag"] == after["@odata.etag"]
        ):
            raise OutlookError("category_endpoint_current_patch_unqualified")
        try:
            self._patch(before, before["categories"])
        except IngestionError as error:
            if error.code != "source_version_changed":
                raise OutlookError("category_endpoint_stale_patch_unqualified") from None
        else:
            raise OutlookError("category_endpoint_ignores_conditional_version")
        final = self.read(message_id)
        if (
            final["categories"] != before["categories"]
            or final["@odata.etag"] != after["@odata.etag"]
        ):
            raise OutlookError("category_qualification_concurrent_edit")
        return CategoryEndpointQualification(
            scope=self.settings.scope,
            writer_client_id=self.settings.writer_identity.client_id,
            checked_at=now,
            expires_at=now + timedelta(days=7),
            probe_reference_sha256=hashlib.sha256(message_id.encode()).hexdigest(),
            current_conditional_patch_verified=True,
            provider_version_changed=True,
            stale_conditional_patch_rejected=True,
            category_membership_preserved=True,
        )
