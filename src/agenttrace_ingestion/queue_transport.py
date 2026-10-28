"""Azure Queue receipt handling: commit locally before deleting the native receipt."""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from agenttrace_foundation.mail_reader import NoRedirect

from .contracts import IngestionError, utc_now
from .notifications import NotificationValidator
from .store import IngestionStore
from .transport import TokenSource, retry_after


class AzureNotificationQueue:
    def __init__(
        self, account: str, token: TokenSource, *, opener: Callable[..., Any] | None = None
    ):
        if not re.fullmatch(r"[a-z0-9]{3,24}", account):
            raise ValueError("invalid_notification_storage_name")
        self.root = f"https://{account}.queue.core.windows.net/mail-notifications/messages"
        self.token = token
        self.open = opener or build_opener(NoRedirect()).open

    def _request(self, method: str, suffix: str) -> bytes:
        for attempt in range(2):
            try:
                request = Request(
                    self.root + suffix,
                    method=method,
                    headers={
                        "Authorization": "Bearer " + self.token(force_refresh=attempt > 0),
                        "x-ms-version": "2023-11-03",
                    },
                )
                with self.open(request, timeout=20) as response:
                    value = response.read(131_073)
                    if len(value) > 131_072 or b"<!DOCTYPE" in value.upper():
                        raise IngestionError("notification_queue_response_invalid")
                    return bytes(value)
            except HTTPError as error:
                if error.code == 401 and not attempt:
                    continue
                raise IngestionError(
                    "notification_queue_throttled"
                    if error.code == 429
                    else "notification_queue_unavailable",
                    retryable=error.code in {408, 429, 500, 502, 503, 504},
                    retry_after=retry_after(error.headers.get("Retry-After")),
                ) from None
            except (URLError, TimeoutError, OSError):
                raise IngestionError(
                    "notification_queue_network_unavailable", retryable=True, retry_after=2
                ) from None
        raise IngestionError("notification_queue_authentication_failed")

    def receive_one(self, store: IngestionStore, validator: NotificationValidator) -> bool:
        raw = self._request("GET", "?numofmessages=1&visibilitytimeout=90")
        message_id, receipt = "", ""
        try:
            root = ET.fromstring(raw)
            message = root.find("QueueMessage")
            if message is None:
                return False
            message_id = message.findtext("MessageId") or ""
            receipt = message.findtext("PopReceipt") or ""
            text = message.findtext("MessageText") or ""
            try:
                payload = (
                    text.encode()
                    if text.lstrip().startswith(("{", "["))
                    else base64.b64decode(text, validate=True)
                )
            except ValueError:
                payload = text.encode()
            items = validator.parse(payload, cloud_events=True)
            store.accept(items)
        except IngestionError as error:
            # Invalid events are not acknowledged; the native delivery age and
            # dequeue count remain observable. Scoped replay is an operator action.
            store.gap(
                validator.enrollment.source_ref,
                "native_notification_validation_failed",
                started_at=utc_now(),
            )
            if (
                message is not None
                and message_id
                and receipt
                and int(message.findtext("DequeueCount") or "1") >= 5
            ):
                store.quarantine_transport(validator.enrollment.source_ref, payload, error.code)
                self._request(
                    "DELETE",
                    "/" + quote(message_id, safe="") + "?popreceipt=" + quote(receipt, safe=""),
                )
                return True
            raise
        except (ValueError, ET.ParseError):
            raise IngestionError("notification_queue_payload_invalid") from None
        if not message_id or not receipt:
            raise IngestionError("notification_queue_receipt_missing")
        self._request(
            "DELETE", "/" + quote(message_id, safe="") + "?popreceipt=" + quote(receipt, safe="")
        )
        return True
