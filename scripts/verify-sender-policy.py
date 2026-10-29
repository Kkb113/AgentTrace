"""Check the approved POC labels and disclosure contract; this is not an accuracy evaluation."""

import json
from pathlib import Path

from agenttrace_outlook.config import CategoryMapping
from agenttrace_outlook.sender_rules import AGENT_RULE, POLICY_VERSION


def main() -> int:
    policy = json.loads(
        (Path(__file__).resolve().parents[1] / "config/outlook-detection-policy.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["policy_version"] == POLICY_VERSION
    assert policy["labels"] == {
        "agent": "AI Agent",
        "compatible_client": CategoryMapping().human,
        "unresolved": "Unknown",
    }
    assert policy["agent_rule"] == AGENT_RULE
    for field in (
        "category_writes_enabled",
        "statistical_accuracy_qualified",
        "human_identity_proof_claimed",
        "independent_forensic_receipt_identity_claimed",
    ):
        assert policy[field] is False
    assert policy["declaration_or_generic_api_alone"] == "Unknown"
    assert policy["failed_or_incomplete_inspection"] == "Unknown"
    print(
        json.dumps(
            {
                "sender_policy_current": True,
                "qualification_basis": "owner_approved_poc_semantics",
                "statistical_accuracy_qualified": False,
                "category_writes_enabled": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
