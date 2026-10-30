"""Private endpoint qualification; automatic monitor activation is still separate."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, model_validator

from .category_contracts import CategorySettings
from .contracts import Record, Scope, Sha256
from .errors import OutlookError


class CategoryEndpointQualification(Record):
    schema_version: Literal["1.0"] = "1.0"
    route: Literal["graph-v1.0-message-categories-if-match/v1"] = (
        "graph-v1.0-message-categories-if-match/v1"
    )
    scope: Scope
    writer_client_id: UUID
    checked_at: AwareDatetime
    expires_at: AwareDatetime
    probe_reference_sha256: Sha256
    current_conditional_patch_verified: Literal[True]
    provider_version_changed: Literal[True]
    stale_conditional_patch_rejected: Literal[True]
    category_membership_preserved: Literal[True]

    @model_validator(mode="after")
    def validity(self) -> "CategoryEndpointQualification":
        if not self.checked_at < self.expires_at <= self.checked_at + timedelta(days=7):
            raise ValueError("invalid_category_qualification_window")
        return self

    def require_current(self, settings: CategorySettings, now: datetime) -> None:
        if (
            self.scope != settings.scope
            or self.writer_client_id != settings.writer_identity.client_id
            or not self.checked_at <= now < self.expires_at
        ):
            raise OutlookError("category_endpoint_not_qualified")
