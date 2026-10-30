"""Separate category setup/ownership contracts; no automatic application is enabled."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .config import ReaderIdentity
from .contracts import Opaque, Record, Scope

Label = Literal["AI Agent", "Human", "Unknown"]
PRESETS: dict[Label, str] = {
    "AI Agent": "preset0",
    "Human": "preset4",
    "Unknown": "preset3",
}


class CategorySettings(Record):
    schema_version: Literal["1.0"] = "1.0"
    scope: Scope
    control_mailbox_id: UUID
    writer_identity: ReaderIdentity
    setup_identity: ReaderIdentity | None = None
    ownership_directory: str = Field(min_length=1, max_length=2048, repr=False)
    automatic_application_enabled: Literal[False] = False

    @field_validator("ownership_directory")
    @classmethod
    def local(cls, value: str) -> str:
        if not Path(value).is_absolute() or value.startswith(("\\\\", "//")):
            raise ValueError("private_local_ownership_directory_required")
        return value

    @model_validator(mode="after")
    def separate_identities(self) -> "CategorySettings":
        if self.control_mailbox_id == self.scope.mailbox_id:
            raise ValueError("distinct_scope_control_required")
        if self.setup_identity and (
            self.setup_identity.client_id == self.writer_identity.client_id
            or self.setup_identity.certificate_thumbprint
            == self.writer_identity.certificate_thumbprint
        ):
            raise ValueError("separate_category_identities_required")
        return self


class MasterCategory(Record):
    id: Opaque = Field(repr=False)
    display_name: str = Field(min_length=1, max_length=255)
    color: str = Field(pattern=r"^preset(?:[0-9]|1[0-9]|2[0-4])$|^none$")

    @field_validator("display_name")
    @classmethod
    def readable(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("category_name_contains_control_character")
        return value


class OwnedCategory(Record):
    label: Label
    category: MasterCategory
    created_at: AwareDatetime
    setup_client_id: UUID | None = None
    creation_receipt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_action_receipt_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def expected_definition(self) -> "OwnedCategory":
        if self.category.display_name != self.label or self.category.color != PRESETS[self.label]:
            raise ValueError("owned_category_definition_mismatch")
        if self.setup_client_id is None and self.owner_action_receipt_sha256 is None:
            raise ValueError("category_ownership_provenance_required")
        return self


class CategoryOwnership(Record):
    schema_version: Literal["1.0"] = "1.0"
    scope: Scope
    writer_client_id: UUID
    created_at: AwareDatetime
    categories: tuple[OwnedCategory, ...] = Field(default=(), max_length=3)
    automatic_application_enabled: Literal[False] = False

    @model_validator(mode="after")
    def unique(self) -> "CategoryOwnership":
        if len({c.label for c in self.categories}) != len(self.categories) or len(
            {c.category.id for c in self.categories}
        ) != len(self.categories):
            raise ValueError("duplicate_category_ownership")
        return self
