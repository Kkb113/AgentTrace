"""Process durable metadata work conservatively; no collection or category mutation yet."""

from __future__ import annotations

from datetime import timedelta

from .contracts import Decision
from .eligibility import UNKNOWN_RULE
from .errors import OutlookError
from .state import StateStore


def run_once(store: StateStore) -> int:
    store.heartbeat()
    processed = 0
    for observation_id, observation in store.pending(store.config.batch_size):
        now = store.clock()
        if observation.observed_at + timedelta(days=7) <= now:
            store.fail_work(observation_id, "observation_expired")
            continue
        decision = Decision(
            scope=observation.scope,
            message_id=observation.message_id,
            source_version=observation.source_version,
            category="Unknown",
            rule_version=UNKNOWN_RULE,
            basis="production",
            qualification="not_required",
            reason_codes=("sender_rules_not_qualified",),
            decided_at=now,
            expires_at=observation.observed_at + timedelta(days=30),
        )
        try:
            store.record_decision(observation_id, decision)
        except OutlookError as error:
            # Storage or fencing failure must stop the worker; never convert it
            # into an actor classification or acknowledge the pending work.
            if error.code in {"lease_lost", "state_transaction_failed", "state_closed"}:
                raise
            store.fail_work(observation_id, "processing_failed")
        else:
            processed += 1
    return processed
