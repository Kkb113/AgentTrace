"""Ingestion records describe observations and gaps, never executor verdicts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr

Axis = Literal["agent", "content"]
SourceKind = Literal["mailbox", "exchange_audit", "office_activity", "graph_activity"]


class IngestionError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: int = 0):
        super().__init__(code)
        self.code, self.retryable, self.retry_after = code, retryable, retry_after


class Enrollment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    source_ref: UUID
    tenant_id: UUID = Field(repr=False)
    mailbox_id: UUID = Field(repr=False)
    collector_client_id: UUID = Field(repr=False)
    folder_ids: tuple[str, ...] = Field(min_length=1, max_length=100, repr=False)
    client_state: SecretStr = Field(min_length=32, max_length=128, repr=False)
    synthetic_subject_prefix: str = "AgentTrace synthetic test:"
    raw_snapshots_allowed: bool = False


class SourceNotification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    source_ref: UUID
    event_ref: UUID
    subscription_ref: str = Field(min_length=1, max_length=256, repr=False)
    message_id: str | None = Field(default=None, max_length=4096, repr=False)
    folder_id: str | None = Field(default=None, max_length=4096, repr=False)
    change: Literal[
        "created", "updated", "deleted", "reauthorizationRequired", "subscriptionRemoved", "missed"
    ]
    event_time: AwareDatetime | None = None
    received_at: AwareDatetime


@dataclass(frozen=True)
class MessageSnapshot:
    immutable_id: str = field(repr=False)
    change_key: str = field(repr=False)
    parent_folder_id: str = field(repr=False)
    internet_message_id: str | None = field(repr=False)
    subject: str = field(repr=False)
    modified_at: datetime
    source_event_at: datetime | None
    is_draft: bool
    copy_role: Literal["sender", "recipient", "unknown"]
    body: str | None = field(default=None, repr=False)
    body_type: str = "text"
    unavailable_reason: str | None = None
    attachment_count: int = 0


def utc_now() -> datetime:
    return datetime.now(UTC)
