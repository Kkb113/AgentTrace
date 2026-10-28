"""Immutable-ID Microsoft Graph reads confined to one enrolled mailbox and folders."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, unquote, urlencode, urlsplit

from .contracts import Enrollment, IngestionError, MessageSnapshot, utc_now
from .transport import MicrosoftTransport

PREFER = {"Prefer": 'IdType="ImmutableId"'}
METADATA = "id,changeKey,parentFolderId,lastModifiedDateTime,internetMessageId,subject,isDraft,sentDateTime,receivedDateTime,hasAttachments"


def instant(value: object) -> datetime:
    if not isinstance(value, str):
        raise IngestionError("source_timestamp_missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise IngestionError("source_timestamp_invalid")
    return result


class MailboxClient:
    def __init__(self, enrollment: Enrollment, transport: MicrosoftTransport):
        self.enrollment, self.transport = enrollment, transport
        self.root = "https://graph.microsoft.com/v1.0/users/" + str(enrollment.mailbox_id)

    def _folder(self, folder: str) -> str:
        if folder not in self.enrollment.folder_ids:
            raise IngestionError("folder_not_enrolled")
        return self.root + "/mailFolders/" + quote(folder, safe="")

    def validate_cursor(self, cursor: str, folder: str) -> str:
        parsed = urlsplit(cursor)
        expected = urlsplit(self._folder(folder) + "/messages/delta")
        path = re.sub(r"/(users|mailFolders)\('([^']+)'\)", r"/\1/\2", unquote(parsed.path))
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or path != unquote(expected.path)
            or parsed.fragment
            or len(cursor) > 32_768
        ):
            raise IngestionError("delta_cursor_out_of_scope")
        return cursor  # Opaque service tokens must be reused verbatim.

    def delta(self, folder: str, cursor: str | None = None) -> dict[str, Any]:
        url = (
            self.validate_cursor(cursor, folder)
            if cursor
            else (
                self._folder(folder)
                + "/messages/delta?"
                + urlencode({"$select": METADATA, "$top": "50"})
            )
        )
        result = self.transport.request("GET", url, headers=PREFER)
        if not isinstance(result.get("value"), list) or len(result["value"]) > 1000:
            raise IngestionError("delta_page_invalid")
        for key in ("@odata.nextLink", "@odata.deltaLink"):
            if key in result:
                self.validate_cursor(result[key], folder)
        if bool(result.get("@odata.nextLink")) == bool(result.get("@odata.deltaLink")):
            raise IngestionError("delta_page_cursor_missing_or_ambiguous")
        return result

    def read(self, message_id: str) -> MessageSnapshot:
        if not message_id or len(message_id) > 4096:
            raise IngestionError("message_identifier_invalid")
        url = self.root + "/messages/" + quote(message_id, safe="")
        metadata = self.transport.request(
            "GET", url + "?" + urlencode({"$select": METADATA}), headers=PREFER
        )
        if metadata.get("id") != message_id:
            raise IngestionError("source_message_identifier_conflict")
        if metadata.get("parentFolderId") not in self.enrollment.folder_ids:
            raise IngestionError("message_moved_out_of_scope")
        if not str(metadata.get("subject", "")).startswith(
            self.enrollment.synthetic_subject_prefix
        ):
            raise IngestionError("message_outside_synthetic_policy")
        reason, body, body_type = None, None, "text"
        try:
            response = self.transport.request(
                "GET",
                url + "?" + urlencode({"$select": "id,changeKey,parentFolderId,body"}),
                headers=PREFER,
            )
            if response.get("changeKey") != metadata.get("changeKey") or response.get(
                "parentFolderId"
            ) != metadata.get("parentFolderId"):
                raise IngestionError("source_version_changed", retryable=True, retry_after=1)
            body = response.get("body", {}).get("content")
            body_type = str(response.get("body", {}).get("contentType", "text")).lower()
            if body is not None and not isinstance(body, str):
                raise IngestionError("source_body_invalid")
            if body is None:
                reason = "body_not_available"
        except IngestionError as error:
            if error.code != "source_access_denied":
                raise
            reason = "body_access_denied_or_protected"
        return MessageSnapshot(
            immutable_id=str(metadata["id"]),
            change_key=str(metadata["changeKey"]),
            parent_folder_id=str(metadata["parentFolderId"]),
            internet_message_id=metadata.get("internetMessageId"),
            subject=str(metadata["subject"]),
            modified_at=instant(metadata.get("lastModifiedDateTime")),
            source_event_at=instant(metadata["sentDateTime"])
            if metadata.get("sentDateTime")
            else None,
            is_draft=bool(metadata.get("isDraft")),
            copy_role="unknown",
            body=body,
            body_type=body_type,
            unavailable_reason=reason,
            attachment_count=int(bool(metadata.get("hasAttachments"))),
        )


class SubscriptionClient:
    """Only subscription maintenance writes; this class cannot write a message."""

    ROOT = "https://graph.microsoft.com/v1.0/subscriptions"

    def __init__(self, mailbox: MailboxClient):
        self.mailbox = mailbox

    def create(self, folder: str, notification_url: str) -> dict[str, Any]:
        self.mailbox._folder(folder)
        if not (
            notification_url.startswith("EventGrid:?") or notification_url.startswith("https://")
        ):
            raise IngestionError("notification_endpoint_invalid")
        return self.mailbox.transport.request(
            "POST",
            self.ROOT,
            headers=PREFER,
            body={
                "changeType": "created,updated,deleted",
                "notificationUrl": notification_url,
                "lifecycleNotificationUrl": notification_url,
                "resource": "users/"
                + str(self.mailbox.enrollment.mailbox_id)
                + "/mailFolders/"
                + quote(folder, safe="")
                + "/messages",
                "expirationDateTime": (utc_now() + timedelta(days=2)).isoformat(),
                "clientState": self.mailbox.enrollment.client_state.get_secret_value(),
                "includeResourceData": False,
            },
        )

    def renew(self, subscription_id: str, *, reauthorize: bool = False) -> dict[str, Any]:
        url = self.ROOT + "/" + quote(subscription_id, safe="")
        if reauthorize:
            return self.mailbox.transport.request("POST", url + "/reauthorize", headers=PREFER)
        return self.mailbox.transport.request(
            "PATCH",
            url,
            headers=PREFER,
            body={
                "expirationDateTime": (utc_now() + timedelta(days=2)).isoformat(),
            },
        )
