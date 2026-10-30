"""Three public labels, readable immutable history and explicit UI ownership provenance."""

import json
from datetime import timedelta

import pytest
from pydantic import ValidationError

from agenttrace_outlook.category_contracts import CategoryOwnership, OwnedCategory
from agenttrace_outlook.config import CategoryMapping
from agenttrace_outlook.contracts import Decision
from agenttrace_outlook.eligibility import require_annotation_eligible
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.sender_rules import HUMAN_RULE, RuleAssessment, evaluate
from tests.unit.test_outlook_categories import decision_for, provisioned
from tests.unit.test_sender_rules import NOW, SCOPE, observation, snapshot


def test_current_rules_and_schemas_expose_only_three_labels():
    expected = {"AI Agent", "Human", "Unknown"}
    assert set(Decision.model_json_schema()["properties"]["category"]["enum"]) == expected
    assert set(RuleAssessment.model_json_schema()["properties"]["category"]["enum"]) == expected
    assert (
        set(
            CategoryOwnership.model_json_schema()["$defs"]["OwnedCategory"]["properties"]["label"][
                "enum"
            ]
        )
        == expected
    )
    assert CategoryMapping().human == "Human"
    assessment = evaluate(observation(), snapshot(), None, NOW)
    assert assessment.category == "Human" and assessment.rule_version == HUMAN_RULE


def test_old_decision_is_readable_but_cannot_bypass_fresh_rule_guard():
    _, current = decision_for(snapshot())
    old = current.model_dump(mode="json")
    old.update(category="Human-capable", rule_version="sender-rules/human-capable/v1")
    archived = json.dumps(old)
    parsed = Decision.model_validate_json(archived)
    assert parsed.category == "Human"
    assert parsed.rule_version == old["rule_version"]
    assert json.loads(archived)["category"] == "Human-capable"
    with pytest.raises(OutlookError, match="not_enrolled_or_qualified"):
        require_annotation_eligible(parsed, SCOPE, NOW)
    old["rule_version"] = HUMAN_RULE
    with pytest.raises(ValidationError):
        Decision.model_validate_json(json.dumps(old))


def test_current_json_round_trip_keeps_strict_dates_and_tuple_validation():
    _, decision = decision_for(snapshot())
    assert Decision.model_validate_json(decision.model_dump_json()) == decision
    legacy = evaluate(observation(), snapshot(), None, NOW).model_dump(mode="json")
    legacy.update(category="Human-capable", rule_version="sender-rules/human-capable/v1")
    parsed = RuleAssessment.model_validate_json(json.dumps(legacy))
    assert parsed.category == "Human" and parsed.rule_version == legacy["rule_version"]


def test_old_private_display_mapping_normalizes_without_adding_a_label():
    mapping = CategoryMapping.model_validate_json('{"human":"Human-capable"}')
    assert mapping.human == "Human"
    assert "Human-capable" not in mapping.model_dump_json()


def test_owner_ui_replacement_needs_provenance_and_keeps_the_color(tmp_path):
    cfg, registry, transport = provisioned(tmp_path)
    human = next(c for c in registry.categories if c.label == "Human")
    raw = human.model_dump(mode="json")
    raw["setup_client_id"] = None
    with pytest.raises(ValidationError, match="provenance_required"):
        OwnedCategory.model_validate_json(json.dumps(raw))
    raw["owner_action_receipt_sha256"] = "a" * 64
    migrated = OwnedCategory.model_validate_json(json.dumps(raw))
    assert migrated.category.color == "preset4" and migrated.label == "Human"
    assert migrated.setup_client_id is None
    assert migrated.created_at <= NOW + timedelta(seconds=1)
