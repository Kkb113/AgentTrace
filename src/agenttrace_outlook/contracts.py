"""Closed observation and decision contracts; evidence qualification is explicit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

Opaque = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:/+=-]{1,2048}$")]
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")]
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Category = Literal["AI Agent", "Human", "Unknown"]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Scope(Record):
    tenant_id: UUID
    mailbox_id: UUID


class Observation(Record):
    schema_version: Literal["1.0"] = "1.0"
    scope: Scope
    message_id: Opaque = Field(repr=False)
    source_version: Opaque = Field(repr=False)
    observed_at: AwareDatetime
    received_at: AwareDatetime
    inspection_complete: bool
    source_digest: Sha256

    @field_validator("observed_at", "received_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def chronology(self) -> Observation:
        if self.received_at > self.observed_at:
            raise ValueError("observation_precedes_receipt")
        return self


class FixtureBatch(Record):
    schema_version: Literal["1.0"] = "1.0"
    synthetic: Literal[True]
    observations: tuple[Observation, ...] = Field(max_length=1000)


class Decision(Record):
    schema_version: Literal["1.0"] = "1.0"
    scope: Scope
    message_id: Opaque = Field(repr=False)
    source_version: Opaque = Field(repr=False)
    rule_version: Opaque
    category: Category
    basis: Literal["production", "experimental"]
    qualification: Literal["qualified", "not_required", "unqualified"]
    reason_codes: tuple[Code, ...] = Field(min_length=1, max_length=32)
    evidence_refs: tuple[Opaque, ...] = Field(default=(), max_length=100)
    decided_at: AwareDatetime
    expires_at: AwareDatetime

    @field_validator("category", mode="before")
    @classmethod
    def historical_label(cls, value: Any, info: ValidationInfo) -> Any:
        # Read old records without rewriting the stored audit payload or rule version.
        # Eligibility still rejects that retired rule for new writes.
        if (
            value == "Human-capable"
            and info.data.get("rule_version") == "sender-rules/human-capable/v1"
        ):
            return "Human"
        return value

    @model_validator(mode="after")
    def semantics(self) -> Decision:
        if self.expires_at <= self.decided_at:
            raise ValueError("decision_expiry_invalid")
        if self.category != "Unknown" and self.qualification == "not_required":
            raise ValueError("positive_category_requires_qualification")
        if (
            self.category != "Unknown"
            and self.qualification == "qualified"
            and not self.evidence_refs
        ):
            raise ValueError("qualified_positive_requires_evidence")
        return self
