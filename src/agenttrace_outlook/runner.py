"""Assess durable metadata work and persist guarded local previews without mailbox writes."""

from __future__ import annotations

from datetime import timedelta

from .contracts import Decision
from .eligibility import UNKNOWN_RULE
from .errors import OutlookError
from .rule_store import RuleStore
from .sender_rules import evaluate
from .state import StateStore


def run_once(store: StateStore) -> int:
    store.heartbeat()
    rules = RuleStore(store)
    rules.prepare()
    processed = 0
    for observation_id, observation in store.pending(store.config.batch_size):
        now = store.clock()
        if observation.observed_at + timedelta(days=7) <= now:
            store.fail_work(observation_id, "observation_expired")
            continue
        snapshot = rules.snapshot(observation)
        assessment = (
            evaluate(
                observation,
                snapshot,
                rules.source(observation_id),
                now,
                providers=store.config.sender_source.agent_providers
                if store.config.sender_source
                else (),
            )
            if snapshot
            else None
        )
        decision = Decision(
            scope=observation.scope,
            message_id=observation.message_id,
            source_version=observation.source_version,
            category=assessment.category if assessment else "Unknown",
            rule_version=assessment.rule_version if assessment else UNKNOWN_RULE,
            basis="production",
            qualification="qualified"
            if assessment and assessment.category != "Unknown"
            else "not_required",
            reason_codes=assessment.reason_codes if assessment else ("sender_rules_not_qualified",),
            evidence_refs=(
                *assessment.evidence_refs,
                "snapshot-sha256:" + observation.source_digest,
            )
            if assessment and assessment.category != "Unknown"
            else assessment.evidence_refs
            if assessment
            else (),
            decided_at=now,
            expires_at=observation.observed_at + timedelta(days=30),
        )
        try:
            store.record_decision(
                observation_id,
                decision,
                assessment_json=assessment.model_dump_json() if assessment else None,
            )
        except OutlookError as error:
            # Storage or fencing failure must stop the worker; never convert it
            # into an actor classification or acknowledge the pending work.
            if error.code in {"lease_lost", "state_transaction_failed", "state_closed"}:
                raise
            store.fail_work(observation_id, "processing_failed")
        else:
            processed += 1
    return processed
