"""Standalone read-only mailbox monitor with durable, evidence-based category previews."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from pydantic import ValidationError

from agenttrace_feasibility.validation import InputError, canonical_bytes, load_json

from .audit_source import certificate_audit
from .config import read_config
from .contracts import FixtureBatch
from .errors import OutlookError
from .reader import certificate_reader
from .rule_store import RuleStore
from .runner import run_once
from .sender_rules import RuleAssessment, sha
from .source_collector import SenderCollector
from .state import StateStore
from .synchronizer import Synchronizer


def emit(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=True, sort_keys=True), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Import a bounded synthetic metadata batch, never decisions or message bodies.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--retry-failed-sources",
        action="store_true",
        help="Requeue blocked analytical-source jobs after fixing their cause; never changes mail.",
    )
    parser.add_argument(
        "--inspect-rules",
        action="store_true",
        help="Read stored POC rule explanations under the state lock without network access or refreshing evidence.",
    )
    parser.add_argument(
        "--retry-failed-sync",
        action="store_true",
        help="Explicitly requeue blocked/dead-letter read jobs without discarding cursors or historical gaps.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration without opening state or connecting to services.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply-categories", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = read_config(args.config)
        if args.apply_categories or (config.mode == "apply_categories" and not args.dry_run):
            raise OutlookError("category_application_not_enabled")
        if args.dry_run:
            config = config.model_copy(update={"mode": "dry_run"})
        fixture = None
        if args.fixture:
            fixture = FixtureBatch.model_validate_json(canonical_bytes(load_json(args.fixture)))
        if config.sync_enabled and fixture:
            raise OutlookError("fixture_and_live_sync_are_separate")
        if args.retry_failed_sync and not config.sync_enabled:
            raise OutlookError("sync_not_enabled")
        if args.retry_failed_sources and config.sender_source is None:
            raise OutlookError("sender_source_not_configured")
        if args.check:
            emit(
                "configuration_valid",
                mode=config.mode,
                runtime_stage="mailbox_sync_dry_run" if config.sync_enabled else "foundation_only",
                category_writes=False,
            )
            return 0
        with StateStore(config) as store:
            if args.inspect_rules:
                emit(
                    "rule_summary",
                    view="stored_assessments",
                    evidence_refreshed=False,
                    **RuleStore(store).summary(),
                )
                with store.transaction(lease=store.lease) as db:
                    rows = db.execute(
                        "SELECT o.message_id,a.payload FROM rule_assessments a JOIN observations o ON o.id=a.observation_id JOIN messages m ON m.current_observation=o.id"
                    ).fetchall()
                    for row in rows:
                        emit(
                            "rule_assessment",
                            message_ref_sha256=sha(row[0]),
                            **RuleAssessment.model_validate_json(row[1]).model_dump(mode="json"),
                        )
                return 0
            sync = Synchronizer(store, certificate_reader(config)) if config.sync_enabled else None
            sender = (
                SenderCollector(
                    store, certificate_audit(config), mail=sync.reader if sync else None
                )
                if config.sender_source
                else None
            )
            if sync and args.retry_failed_sync:
                emit("sync_requeued", jobs=sync.state.retry_failed())
            if sender and args.retry_failed_sources:
                emit("sources_requeued", jobs=sender.rules.retry_failed())
            if fixture:
                accepted = store.observe(fixture.observations)
                emit("fixture_imported", accepted=accepted, synthetic=True)
            emit(
                "ready",
                mode="dry_run",
                mailbox_collection="read_only_delta" if sync else "disabled",
                actor_rules="corroborated_poc_ai_and_human_label",
                category_writes=False,
            )
            while True:
                if sync:
                    sync.run_cycle()
                    emit("sync_cycle_completed", **sync.state.summary())
                if sender:
                    sender.step()
                    emit("sender_sources", **sender.rules.summary())
                processed = run_once(store)
                emit("cycle_completed", processed=processed, **store.summary())
                if args.once:
                    return (
                        1
                        if (sync and sync.state.summary()["sync_health"] == "degraded")
                        or (sender and sender.rules.summary()["source_blocked"])
                        else 0
                    )
                time.sleep(config.poll_seconds)
    except KeyboardInterrupt:
        emit("stopped", reason="operator_interrupt", category_writes=False)
        return 0
    except OutlookError as error:
        emit("error", code=error.code, category_writes=False)
        return 1
    except (InputError, ValidationError, OSError, ValueError, sqlite3.Error):
        emit("error", code="invalid_input_or_runtime_unavailable", category_writes=False)
        return 1
    except Exception:
        # Last-resort process boundary: never print third-party exception text,
        # tokens, URLs or source data, and never turn a failure into a verdict.
        emit("error", code="unexpected_runtime_failure", category_writes=False)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
