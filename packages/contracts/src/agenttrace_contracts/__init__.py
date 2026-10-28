"""Versioned product contracts; text origin cannot influence send attribution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Reason = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,99}$")]
Reference = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/+=-]{0,255}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class AgentSendFinding(Contract):
    status: Literal["verified_agent", "no_agent_observed_in_monitored_path", "unknown"]
    flagged: bool | None
    reason_codes: list[Reason] = Field(min_length=1, max_length=32)
    evidence_refs: list[Reference] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def consistent_flag(self) -> AgentSendFinding:
        expected = {
            "verified_agent": True,
            "no_agent_observed_in_monitored_path": False,
            "unknown": None,
        }
        if self.flagged is not expected[self.status]:
            raise ValueError("agent_flag_must_match_status")
        if self.flagged is True and not self.evidence_refs:
            raise ValueError("positive_agent_finding_requires_evidence")
        return self


class ContentAssessment(Contract):
    status: Literal[
        "verified_ai_content",
        "likely_ai_content",
        "no_ai_signal_detected",
        "inconclusive",
        "unknown",
    ]
    flagged: bool | None
    reason_codes: list[Reason] = Field(min_length=1, max_length=32)
    evidence_refs: list[Reference] = Field(default_factory=list, max_length=100)
    score: float | None = Field(default=None, ge=0, le=1)
    qualification: Literal["not_run", "experimental", "qualified", "provenance"] = "not_run"
    calibration_ref: Reference | None = None

    @model_validator(mode="after")
    def consistent_flag(self) -> ContentAssessment:
        expected = {
            "verified_ai_content": True,
            "likely_ai_content": True,
            "no_ai_signal_detected": False,
            "inconclusive": None,
            "unknown": None,
        }
        if self.flagged is not expected[self.status]:
            raise ValueError("content_flag_must_match_status")
        if self.status == "likely_ai_content" and (
            self.qualification != "qualified" or self.score is None or self.calibration_ref is None
        ):
            raise ValueError("statistical_positive_requires_qualified_calibration")
        if self.status == "verified_ai_content" and (
            self.qualification != "provenance" or not self.evidence_refs
        ):
            raise ValueError("verified_content_requires_inclusion_provenance")
        return self


class DetectionFindings(Contract):
    agent_send_attribution: AgentSendFinding
    content_assessment: ContentAssessment


class DetectionDecision(Contract):
    schema_version: Literal["1.0"] = "1.0"
    decision_id: UUID
    message_ref: Reference
    observed_at: AwareDatetime
    validation_basis: Literal[
        "authored_contract_example", "live_authenticated_evidence", "unverified"
    ]
    findings: DetectionFindings


class DetectionJob(Contract):
    schema_version: Literal["1.0"] = "1.0"
    fixture_ref: Literal["authored_contract_example"]
    message_ref: Reference


def unknown_content(reason: Reason = "content_model_not_installed") -> ContentAssessment:
    return ContentAssessment(status="unknown", flagged=None, reason_codes=[reason])


def utc_now() -> datetime:
    return datetime.now(UTC)
