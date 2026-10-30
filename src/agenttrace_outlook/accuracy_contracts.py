"""Sender-only study contracts. Labels and custody records never enter detector input."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from .agent_providers import AgentProvider
from .contracts import Code, Observation, Opaque, Record, Scope, Sha256

Actor = Literal["human", "ai_agent", "non_ai_automation", "unresolved"]
Split = Literal["development", "calibration", "evaluation"]
Route = Literal["outlook_to_outlook", "gmail_to_outlook", "outlook_to_gmail", "gmail_to_gmail"]


class Asset(Record):
    path: str = Field(min_length=1, max_length=240, repr=False)
    sha256: Sha256
    collected_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def retention(self) -> Asset:
        if not self.collected_at < self.expires_at <= self.collected_at + timedelta(days=7):
            raise ValueError("raw_retention_invalid")
        return self


class Enrollment(Record):
    scope: Scope
    mailbox_address: str = Field(pattern=r"^[^\s<>@]+@[^\s<>@]+$", repr=False)
    exchange_mailbox_guid: str = Field(min_length=1, max_length=100, repr=False)
    publisher_id: str = Field(min_length=1, max_length=100)
    publisher_owner_tenant: str = Field(min_length=1, max_length=100)
    agent_providers: tuple[AgentProvider, ...] = Field(default=(), max_length=20)


class SourceCapture(Record):
    """Raw replay material, not an assertion that JSON authenticates its own source."""

    state: Literal["complete", "pending", "unavailable"]
    captured_at: AwareDatetime
    expires_at: AwareDatetime
    query: dict[str, Any] = Field(default_factory=dict, repr=False)
    query_id: Opaque | None = None
    records: tuple[dict[str, Any], ...] = Field(default=(), max_length=1000, repr=False)
    publisher: dict[str, Any] = Field(default_factory=dict, repr=False)
    copies: tuple[dict[str, Any], ...] = Field(default=(), max_length=1000, repr=False)
    sent_folder_id: Opaque | None = Field(default=None, repr=False)
    pagination_complete: bool = False

    @model_validator(mode="after")
    def freshness(self) -> SourceCapture:
        if not self.captured_at < self.expires_at <= self.captured_at + timedelta(minutes=5):
            raise ValueError("source_freshness_invalid")
        return self


class Frame(Record):
    available_at: AwareDatetime
    snapshot: dict[str, Any] | None = Field(default=None, repr=False)
    source: SourceCapture | None = None


class DetectorPacket(Record):
    observation: Observation
    frames: tuple[Frame, ...] = Field(max_length=2000)

    @model_validator(mode="after")
    def chronology(self) -> DetectorPacket:
        times = [f.available_at for f in self.frames]
        if times != sorted(set(times)) or any(t < self.observation.observed_at for t in times):
            raise ValueError("frame_chronology_invalid")
        if any(f.source and f.source.captured_at > f.available_at for f in self.frames):
            raise ValueError("frame_precedes_capture")
        return self


class Groups(Record):
    sender: Code
    workflow: Code
    thread: Code
    template: Code
    source: Code
    independence_cluster: Code


class Reviewer(Record):
    reviewer_ref: Code
    kind: Literal["human", "fictional_test_identity"]
    independent_of_detector: bool


class ActionReview(Record):
    reviewer_ref: Code
    actor: Actor
    reviewed_at: AwareDatetime
    blind_to_predictions: bool
    action_source_verified: bool
    capture_custody_verified: bool
    adjudication: bool = False
    input_sha256: Sha256
    action_sha256: Sha256
    rights_sha256: Sha256
    case_sha256: Sha256
    attestation: Asset


class EvaluationCase(Record):
    case_ref: Code
    basis: Literal["independent_action_history", "owner_reported_pilot", "authored_adversarial"]
    split: Split
    actor: Actor
    approval: Literal["approved", "autonomous", "none", "unknown"]
    creator_ref: Code
    prepared_at: AwareDatetime
    time_basis: Literal["send_record", "operator_attestation", "collection_only"]
    route: Route
    source_family: Code
    population: Code
    supported_agent_path: bool
    families: tuple[Code, ...] = Field(min_length=1, max_length=30)
    groups: Groups
    text_sha256: Sha256 | None = None  # Grouping only, never supplied to the detector.
    input: Asset
    action: Asset
    rights: Asset
    message: Asset | None = None  # Optional synthetic EML, used only for leakage checks.
    reviews: tuple[ActionReview, ...] = Field(default=(), max_length=3)


class AccuracyDataset(Record):
    schema_version: Literal["1.0"] = "1.0"
    study_ref: Code
    usage: Literal["curator_study", "development_export"] = "curator_study"
    synthetic_only: Literal[True]
    detector_sha256: Sha256
    policy_sha256: Sha256
    enabled_populations: tuple[Code, ...] = Field(min_length=1)
    declared_blind_spots: tuple[Code, ...] = Field(min_length=1)
    enrollments: tuple[Enrollment, ...] = Field(default=(), max_length=100)
    reviewers: tuple[Reviewer, ...] = Field(default=(), max_length=100)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def unique(self) -> AccuracyDataset:
        for values in (
            [c.case_ref for c in self.cases],
            [r.reviewer_ref for r in self.reviewers],
            [e.scope.model_dump_json() for e in self.enrollments],
        ):
            if len(values) != len(set(values)):
                raise ValueError("duplicate_study_identity")
        return self


def review_binding(case: EvaluationCase) -> str:
    """Bind grouping/scope/source assets while preserving independent disagreements."""
    return hashlib.sha256(case.model_dump_json(exclude={"reviews", "actor"}).encode()).hexdigest()
