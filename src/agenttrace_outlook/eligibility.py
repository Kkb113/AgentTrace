"""Pure future writer boundary; it performs no network operation."""

from datetime import datetime

from .contracts import Decision, Scope
from .errors import OutlookError
from .sender_rules import AGENT_RULE, HUMAN_RULE, PROVIDER_RULE

UNKNOWN_RULE = "foundation/unknown/v1"
SENDER_UNKNOWN_RULE = "sender-rules/unknown/v1"


def require_annotation_eligible(decision: Decision, scope: Scope, now: datetime) -> None:
    if decision.scope != scope:
        raise OutlookError("decision_scope_mismatch")
    if decision.basis != "production":
        raise OutlookError("experimental_decision_rejected")
    if not decision.decided_at <= now < decision.expires_at:
        raise OutlookError("decision_outside_validity")
    if (
        decision.category == "Human"
        and decision.rule_version == HUMAN_RULE
        and decision.qualification == "qualified"
        and any(ref.startswith("snapshot-sha256:") for ref in decision.evidence_refs)
    ):
        return
    if (
        decision.category == "AI Agent"
        and decision.rule_version in {AGENT_RULE, PROVIDER_RULE}
        and decision.qualification == "qualified"
        and all(
            any(ref.startswith(prefix) for ref in decision.evidence_refs)
            for prefix in ("audit-sha256:", "publisher-sha256:", "snapshot-sha256:")
            + (("provider-sha256:",) if decision.rule_version == PROVIDER_RULE else ())
        )
    ):
        return
    if (
        decision.category != "Unknown"
        or decision.rule_version not in {UNKNOWN_RULE, SENDER_UNKNOWN_RULE}
        or decision.qualification != "not_required"
    ):
        # No positive rule has been independently qualified at this milestone.
        raise OutlookError("rule_not_enrolled_or_qualified")
