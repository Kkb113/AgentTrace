"""Closed, versioned evidence claims. Claims never enroll their own issuer."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from agenttrace_contracts import Contract
from pydantic import AwareDatetime, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_./-]{0,63}$")]
Kind = Literal["send_execution", "generation", "content_inclusion", "content_edit", "copy_mapping"]


class Identifier(Contract):
    kind: Literal["mailbox_immutable", "internet_message_id"]
    value: str = Field(min_length=1, max_length=2048, repr=False)


class SendExecution(Contract):
    kind: Literal["send_execution"] = "send_execution"
    outcome: Literal["attempted", "accepted", "completed", "failed"]
    actor: Literal["ai_agent", "human", "non_ai_application", "unknown"]
    execution_ref: UUID
    actor_ref: UUID
    application_ref: UUID
    workflow_version: Version
    mechanism: Literal["agent", "human_interaction_observed", "conventional_automation", "unknown"]
    link_method: Literal["exact_identifier", "candidate", "unsupported"]
    identifier: Identifier | None = None

    @model_validator(mode="after")
    def bound_identifier(self) -> SendExecution:
        if self.link_method == "exact_identifier" and self.identifier is None:
            raise ValueError("exact_link_requires_identifier")
        return self


class Generation(Contract):
    kind: Literal["generation"] = "generation"
    output_sha256: Digest = Field(repr=False)
    origin: Literal["new_generated_output", "echoed_human_input", "shared_template", "unknown"]
    operation: Literal[
        "draft_generation", "substantial_rewrite", "translation_into_english", "basic_correction"
    ]
    provider_ref: Version | None = None
    model_ref: Version | None = None


class ContentInclusion(Contract):
    kind: Literal["content_inclusion"] = "content_inclusion"
    generation_ref: UUID
    method: Literal[
        "authenticated_transfer_lineage", "exact_output_match", "fuzzy_similarity", "unsupported"
    ]
    region_start: int = Field(ge=0)
    region_end: int = Field(gt=0)
    output_sha256: Digest = Field(repr=False)


class ContentEdit(Contract):
    kind: Literal["content_edit"] = "content_edit"
    parent_inclusion_ref: UUID
    method: Literal["authenticated_unchanged_span", "changed_output", "unsupported"]
    before_sha256: Digest = Field(repr=False)
    after_sha256: Digest = Field(repr=False)
    region_start: int = Field(ge=0)
    region_end: int = Field(gt=0)


class CopyMapping(Contract):
    kind: Literal["copy_mapping"] = "copy_mapping"
    other_message_ref: UUID
    other_version_ref: UUID
    relation: Literal[
        "delivery_copy", "documented_id_translation", "archive_move", "forward_context"
    ]
    mapping_basis: Literal["authenticated_source_mapping", "similarity_only"]


Fact = Annotated[
    SendExecution | Generation | ContentInclusion | ContentEdit | CopyMapping,
    Field(discriminator="kind"),
]


class EvidenceRecord(Contract):
    schema_version: Literal["1.0"] = "1.0"
    canonicalization_version: Literal["evidence-json-v1"] = "evidence-json-v1"
    issuer_ref: UUID
    event_id: UUID
    tenant_id: UUID
    mailbox_id: UUID
    message_ref: UUID
    version_ref: UUID
    occurred_at: AwareDatetime
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    source_schema_version: Version
    source_request_ref: UUID | None = None
    fact: Fact

    @model_validator(mode="after")
    def bounded_lifetime(self) -> EvidenceRecord:
        if (
            not self.occurred_at
            <= self.issued_at
            < self.expires_at
            <= self.occurred_at + timedelta(days=7)
        ):
            raise ValueError("invalid_evidence_lifetime")
        return self


class SignedEvidence(Contract):
    algorithm: Literal["Ed25519"] = "Ed25519"
    key_ref: UUID
    record: EvidenceRecord
    signature: str = Field(pattern=r"^[A-Za-z0-9+/]{86}==$", repr=False)


class Region(Contract):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    role: Literal["authored", "inherited"]


class Recipient(Contract):
    role: Literal["to", "cc", "bcc"]
    address: str = Field(min_length=3, max_length=320, repr=False)


class MessageObservation(Contract):
    tenant_id: UUID
    mailbox_id: UUID
    source_ref: UUID
    source_event_ref: UUID
    source_schema_version: Version
    namespace: Literal["graph_immutable", "exchange_store", "external_source"]
    immutable_id: str = Field(min_length=1, max_length=2048, repr=False)
    internet_message_id: str | None = Field(default=None, min_length=1, max_length=2048, repr=False)
    version_ref: UUID
    copy_role: Literal["sender", "recipient", "unknown"]
    state: Literal["draft", "sent", "received", "unknown"]
    observed_at: AwareDatetime
    source_event_at: AwareDatetime | None = None
    sent_at: AwareDatetime | None = None
    subject: str = Field(max_length=2048, repr=False)
    body: str = Field(max_length=262144, repr=False)
    content_available: bool = True
    recipients: tuple[Recipient, ...] = Field(max_length=200, repr=False)
    recipients_complete: bool = True
    regions: tuple[Region, ...] = Field(default=(), max_length=64)
    transport_bytes_sha256: Digest | None = Field(default=None, repr=False)
    snapshot_ref: UUID | None = None
    snapshot_expires_at: AwareDatetime | None = None
    snapshot_authorized: bool = False
    normalization_version: Version = "mail-text-v1"

    @model_validator(mode="after")
    def snapshot_policy(self) -> MessageObservation:
        if not self.content_available and (self.body or self.regions):
            raise ValueError("unavailable_content_must_not_supply_text_or_regions")
        if self.snapshot_ref is not None:
            if not self.snapshot_authorized or self.snapshot_expires_at is None:
                raise ValueError("snapshot_requires_explicit_authorization_and_expiry")
        elif self.snapshot_expires_at is not None or self.snapshot_authorized:
            raise ValueError("snapshot_policy_without_reference")
        return self


class CorrelationLink(Contract):
    evidence_ref: UUID
    source_ref: UUID
    key_ref: UUID
    record_digest: Digest
    schema_version: Literal["1.0"]
    source_schema_version: Version | None = None
    occurred_at: AwareDatetime | None = None
    ingested_at: AwareDatetime
    classification: Literal[
        "exact", "candidate", "unsupported", "context", "invalid", "conflicting", "exact_mapping"
    ]
    reason: Version
    actor: Literal["ai_agent", "human", "non_ai_application", "unknown"] | None = None
    execution_ref: UUID | None = None
    parent_ref: UUID | None = None
    relation: (
        Literal["delivery_copy", "documented_id_translation", "archive_move", "forward_context"]
        | None
    ) = None


class ObservationSource(Contract):
    source_ref: UUID
    source_event_ref: UUID
    schema_version: Version
    normalization_version: Version
    canonicalization_version: Literal["mail-text-v1"]
    observation_digest: Digest
    capture_basis: Literal["synthetic_fixture", "committed_ingestion"]
    content_available: bool
    recipients_complete: bool
    source_event_at: AwareDatetime | None
    observed_at: AwareDatetime


class Correlations(Contract):
    agent_send_attribution: list[CorrelationLink]
    content_assessment: list[CorrelationLink]


class ReplayCapability(Contract):
    snapshot_ref: UUID | None
    snapshot_reference_within_retention: bool
    snapshot_bytes_verified: Literal[False] = False
    model_reexecution_available: Literal[False] = False
    reason: Literal["model_not_installed_and_artifacts_not_pinned"]


class CorrelationView(Contract):
    schema_version: Literal["1.0"]
    rule_version: Literal["correlation-v1"]
    message_ref: UUID
    version_ref: UUID
    source: ObservationSource
    current_message_version: bool
    correlations: Correlations
    copy_mappings: list[CorrelationLink]
    replay: ReplayCapability
    qualification: Literal["evidence_correlation_only_not_a_detection_accuracy_claim"]
