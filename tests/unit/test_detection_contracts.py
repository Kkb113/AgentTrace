import json
from pathlib import Path
from uuid import uuid4

import pytest
from agenttrace_attribution import assess_authored_example
from agenttrace_content_detection import ContentSample, UnavailableContentScorer
from agenttrace_contracts import (
    AgentSendFinding,
    ContentAssessment,
    DetectionDecision,
    DetectionFindings,
    utc_now,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def findings():
    return DetectionFindings(
        agent_send_attribution=AgentSendFinding(
            status="unknown", flagged=None, reason_codes=["missing_evidence"]
        ),
        content_assessment=ContentAssessment(
            status="unknown", flagged=None, reason_codes=["not_scored"]
        ),
    )


@pytest.mark.parametrize(
    "status,flag",
    [("unknown", True), ("verified_agent", False), ("no_agent_observed_in_monitored_path", None)],
)
def test_agent_flags_cannot_contradict_status(status, flag):
    with pytest.raises(ValidationError):
        AgentSendFinding(
            status=status, flagged=flag, reason_codes=["example"], evidence_refs=["record"]
        )


def test_primary_contract_has_no_content_score_or_sender_operation():
    for extra in [{"content_score": 0.9}, {"send_mail": True}, {"approval": "approved"}]:
        with pytest.raises(ValidationError):
            AgentSendFinding(status="unknown", flagged=None, reason_codes=["example"], **extra)


def test_verified_agent_requires_evidence():
    with pytest.raises(ValidationError):
        AgentSendFinding(status="verified_agent", flagged=True, reason_codes=["example"])


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_content_score_is_finite_and_bounded(score):
    with pytest.raises(ValidationError):
        ContentAssessment(
            status="inconclusive", flagged=None, score=score, reason_codes=["example"]
        )


def test_experimental_score_cannot_become_positive_flag():
    with pytest.raises(ValidationError):
        ContentAssessment(
            status="likely_ai_content",
            flagged=True,
            score=0.99,
            qualification="experimental",
            reason_codes=["example"],
        )


def test_exactly_two_findings_and_utc_timestamp_are_required():
    value = DetectionDecision(
        decision_id=uuid4(),
        message_ref="example",
        observed_at=utc_now(),
        validation_basis="authored_contract_example",
        findings=findings(),
    )
    assert set(value.model_dump()["findings"]) == {"agent_send_attribution", "content_assessment"}
    raw = json.loads(value.model_dump_json())
    raw["findings"]["third_finding"] = {}
    with pytest.raises(ValidationError):
        DetectionDecision.model_validate_json(json.dumps(raw))
    raw.pop("findings")
    with pytest.raises(ValidationError):
        DetectionDecision.model_validate_json(json.dumps(raw))


def test_public_fixture_maps_through_typed_adapter():
    result = assess_authored_example(ROOT / "examples/evidence-contract")
    assert result.agent_send_attribution.flagged is True
    assert result.content_assessment.flagged is None


def test_model_absence_and_unsupported_language_are_explicit_unknowns():
    scorer = UnavailableContentScorer()
    for language in ["en", "unsupported"]:
        sample = ContentSample(text="Private transient text", language=language)
        assert "Private transient text" not in repr(sample)
        assert scorer.assess(sample).flagged is None
