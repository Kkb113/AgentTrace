"""Validated local runtime configuration, deliberately separate from the frozen baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, ValidationError, field_validator, model_validator

from agenttrace_feasibility.validation import InputError, canonical_bytes, load_json

from .contracts import Record, Scope
from .errors import OutlookError


class CategoryMapping(Record):
    ai_agent: Literal["AI Agent"] = "AI Agent"
    human: Literal["Human"] = "Human"
    unknown: Literal["Unknown"] = "Unknown"
    ai_color: Literal["preset0"] = "preset0"
    human_color: Literal["preset4"] = "preset4"
    unknown_color: Literal["preset3"] = "preset3"


class ReaderIdentity(Record):
    client_id: UUID
    certificate_thumbprint: str = Field(pattern=r"^[a-fA-F0-9]{40}$", repr=False)


class RuntimeConfig(Record):
    schema_version: Literal["1.0"] = "1.0"
    profile: Literal["outlook_foundation"] = "outlook_foundation"
    scope: Scope
    state_directory: str = Field(min_length=1, max_length=2048, repr=False)
    mode: Literal["dry_run", "apply_categories"] = "dry_run"
    categories: CategoryMapping = Field(default_factory=CategoryMapping)
    reader_identity: ReaderIdentity | None = None
    poll_seconds: int = Field(default=10, ge=1, le=60)
    lease_seconds: int = Field(default=120, ge=30, le=600)
    batch_size: int = Field(default=50, ge=1, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    raw_retention_days: Literal[7] = 7
    decision_retention_days: Literal[30] = 30
    data_boundary: Literal["synthetic_only"] = "synthetic_only"
    production_positive_rules: tuple[str, ...] = ()
    sync_enabled: bool = False
    sync_poll_seconds: int = Field(default=30, ge=10, le=600)
    folder_refresh_seconds: int = Field(default=300, ge=60, le=3600)
    sync_operations_per_cycle: int = Field(default=10, ge=1, le=100)
    page_size: int = Field(default=100, ge=1, le=100)
    backfill_since: AwareDatetime | None = None
    synthetic_subject_prefix: Literal["AgentTrace synthetic test:"] = "AgentTrace synthetic test:"

    @field_validator("state_directory")
    @classmethod
    def local_absolute(cls, value: str) -> str:
        if not Path(value).is_absolute() or value.startswith(("\\\\", "//")) or "://" in value:
            raise ValueError("local_absolute_state_directory_required")
        return value

    @model_validator(mode="after")
    def safe_foundation(self) -> RuntimeConfig:
        if self.production_positive_rules:
            raise ValueError("positive_rules_not_qualified_in_foundation")
        if self.sync_enabled and self.reader_identity is None:
            raise ValueError("sync_reader_identity_required")
        if self.sync_enabled and self.lease_seconds < 120:
            raise ValueError("sync_lease_too_short_for_bounded_network_calls")
        if self.lease_seconds < self.poll_seconds * 3:
            raise ValueError("lease_too_short_for_poll_interval")
        return self


def read_config(path: Path) -> RuntimeConfig:
    try:
        return RuntimeConfig.model_validate_json(canonical_bytes(load_json(path)))
    except (InputError, ValidationError, OSError, ValueError):
        raise OutlookError("invalid_configuration") from None
