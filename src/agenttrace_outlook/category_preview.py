"""Read-only current-evidence preview; no writer, intent or apply flag is available."""

from datetime import datetime
from typing import Any

from .category_contracts import CategoryOwnership, MasterCategory
from .category_ownership import verify_ownership
from .contracts import Decision, Observation
from .eligibility import require_annotation_eligible
from .errors import OutlookError
from .sender_rules import evaluate


def category_preview(
    registry: CategoryOwnership,
    inventory: tuple[MasterCategory, ...],
    decision: Decision,
    observation: Observation,
    snapshot: dict[str, Any] | None,
    source: dict[str, Any] | None,
    message: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    verify_ownership(registry, inventory)
    require_annotation_eligible(decision, registry.scope, now)
    if (
        observation.scope != registry.scope
        or observation.message_id != decision.message_id
        or observation.source_version != decision.source_version
    ):
        raise OutlookError("category_preview_observation_mismatch")
    if decision.rule_version.startswith("sender-rules/"):
        current = evaluate(observation, snapshot, source, now)
        if current.category != decision.category or current.rule_version != decision.rule_version:
            raise OutlookError("category_preview_evidence_stale")
        if tuple(current.reason_codes) != decision.reason_codes:
            raise OutlookError("category_preview_evidence_changed")
    if (
        message.get("id") != decision.message_id
        or message.get("isDraft") is not False
        or not str(message.get("subject", "")).startswith("AgentTrace synthetic test:")
    ):
        raise OutlookError("category_preview_synthetic_message_required")
    categories = message.get("categories")
    if (
        not isinstance(categories, list)
        or any(not isinstance(c, str) for c in categories)
        or len(set(categories)) != len(categories)
    ):
        raise OutlookError("category_preview_current_categories_invalid")
    managed = {c.category.display_name for c in registry.categories}
    desired = next(
        c.category.display_name for c in registry.categories if c.label == decision.category
    )
    after = [c for c in categories if c not in managed] + [desired]
    return {
        "category": decision.category,
        "would_change": set(after) != set(categories),
        "unrelated_categories_preserved": all(c in after for c in categories if c not in managed),
        "managed_categories_after": 1,
        "automatic_application_enabled": False,
        "mailbox_mutation_performed": False,
        "desired_category_id": next(
            c.category.id for c in registry.categories if c.label == decision.category
        ),
    }
