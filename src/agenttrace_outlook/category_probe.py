"""One-shot approved category access probe; its sole PATCH is an unchanged array."""

import json
from typing import Any
from urllib.parse import quote
from uuid import UUID

from agenttrace_ingestion.contracts import IngestionError

from .category_contracts import CategorySettings
from .errors import OutlookError


class CategoryPermissionProbe:
    def __init__(self, settings: CategorySettings, transport: Any):
        self.settings, self.transport = settings, transport
        self.base = "https://graph.microsoft.com/v1.0/users/"
        self._captured: dict[str, Any] | None = None

    def metadata(self, message_id: str) -> dict[str, Any]:
        if not 1 <= len(message_id) <= 2048:
            raise OutlookError("invalid_category_probe_message")
        url = (
            self.base
            + str(self.settings.scope.mailbox_id)
            + "/messages/"
            + quote(message_id, safe="")
            + "?$select=id,subject,isDraft,categories,changeKey"
        )
        result: dict[str, Any] = self.transport.request(
            "GET", url, headers={"Prefer": 'IdType="ImmutableId"'}
        )
        if (
            result.get("id") != message_id
            or result.get("isDraft") is not False
            or not isinstance(result.get("subject"), str)
            or not result["subject"].startswith("AgentTrace synthetic test:")
            or not isinstance(result.get("categories"), list)
            or any(not isinstance(c, str) for c in result["categories"])
            or not isinstance(result.get("@odata.etag"), str)
        ):
            raise OutlookError("synthetic_non_draft_versioned_probe_required")
        self._captured = json.loads(json.dumps(result))
        return result

    def unchanged_patch(self, metadata: dict[str, Any], *, mailbox_id: UUID) -> dict[str, Any]:
        if mailbox_id not in {self.settings.scope.mailbox_id, self.settings.control_mailbox_id}:
            raise OutlookError("category_probe_mailbox_not_allowlisted")
        if self._captured is None or metadata != self._captured:
            raise OutlookError("category_probe_requires_unchanged_read_receipt")
        if (
            metadata.get("isDraft") is not False
            or not str(metadata.get("subject", "")).startswith("AgentTrace synthetic test:")
            or not isinstance(metadata.get("categories"), list)
            or any(not isinstance(c, str) for c in metadata["categories"])
            or not isinstance(metadata.get("@odata.etag"), str)
            or not isinstance(metadata.get("id"), str)
            or not 1 <= len(metadata["id"]) <= 2048
        ):
            raise OutlookError("synthetic_non_draft_versioned_probe_required")
        # There is no desired-category argument: this cannot apply a verdict.
        result: dict[str, Any] = self.transport.request(
            "PATCH",
            self.base + str(mailbox_id) + "/messages/" + quote(metadata["id"], safe=""),
            body={"categories": metadata["categories"]},
            headers={"Prefer": 'IdType="ImmutableId"', "If-Match": metadata["@odata.etag"]},
        )
        return result

    def denied_outside_scope(self, metadata: dict[str, Any]) -> dict[str, bool]:
        results = {}
        paths = {
            "negative_mail_read_denied": self.base
            + str(self.settings.control_mailbox_id)
            + "/mailFolders/inbox/messages?$select=id&$top=1",
            "negative_category_read_denied": self.base
            + str(self.settings.control_mailbox_id)
            + "/outlook/masterCategories?$select=id,displayName,color",
        }
        for name, path in paths.items():
            try:
                self.transport.request("GET", path)
            except IngestionError as error:
                if error.code != "source_access_denied":
                    raise
                results[name] = True
            else:
                raise OutlookError("unexpected_out_of_scope_category_access")
        try:
            self.unchanged_patch(metadata, mailbox_id=self.settings.control_mailbox_id)
        except IngestionError as error:
            if error.code != "source_access_denied":
                raise
            results["negative_mailbox_path_patch_denied"] = True
        else:
            raise OutlookError("unexpected_out_of_scope_category_write")
        return results
