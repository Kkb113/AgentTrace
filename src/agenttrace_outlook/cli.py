"""Mailbox monitor with explicit opt-in to scoped, evidence-based Outlook labels."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from contextlib import ExitStack
from pathlib import Path

from pydantic import ValidationError

from agenttrace_feasibility.validation import InputError, canonical_bytes, load_json

from .audit_source import certificate_audit
from .category_application import ApplicationSettings, CategoryApplication
from .category_catalog import certificate_catalog
from .category_ownership import OwnershipStore, verify_ownership
from .category_writer import CategoryWriter
from .config import read_config
from .contracts import FixtureBatch
from .errors import OutlookError
from .reader import certificate_reader
from .rule_store import RuleStore
from .runner import run_once
from .sender_rules import RuleAssessment, sha
from .source_collector import SenderCollector
from .source_worker import SourceWorker
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
    parser.add_argument("--category-settings", type=Path)
    parser.add_argument("--category-qualification", type=Path)
    args = parser.parse_args(argv)
    application = None
    writes_enabled = False
    try:
        config = read_config(args.config)
        if config.mode == "apply_categories" and not (args.apply_categories or args.dry_run):
            raise OutlookError("category_application_not_enabled")
        # The state engine remains a non-writing collector. Only this explicit flag
        # can connect its decisions to the independently authenticated writer.
        config = config.model_copy(update={"mode": "dry_run"})
        if args.apply_categories:
            if (
                args.category_settings is None
                or args.category_qualification is None
                or args.fixture
                or args.inspect_rules
            ):
                raise OutlookError("explicit_live_category_configuration_required")
            application = ApplicationSettings.read(
                config, args.category_settings, args.category_qualification
            )
        elif args.category_settings or args.category_qualification:
            raise OutlookError("category_settings_require_apply_flag")
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
                mode="apply_categories" if application else "dry_run",
                runtime_stage=("mailbox_sync_apply" if application else "mailbox_sync_dry_run")
                if config.sync_enabled
                else "foundation_only",
                category_writes=False,
                category_application_requested=application is not None,
            )
            return 0
        with ExitStack() as resources:
            store = resources.enter_context(StateStore(config))
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
            category_application = None
            if application:
                ownership = OwnershipStore(application.settings)
                resources.callback(ownership.close)
                registry = ownership.load()
                if registry is None:
                    raise OutlookError("category_ownership_required")
                catalog = certificate_catalog(application.settings, "writer")
                verify_ownership(registry, catalog.inventory())
                category_application = CategoryApplication(
                    CategoryWriter(store, catalog, registry, application.qualification)
                )
                writes_enabled = True
            sync = Synchronizer(store, certificate_reader(config)) if config.sync_enabled else None
            sender = (
                SenderCollector(
                    store,
                    certificate_audit(config),
                    mail=certificate_reader(config)
                    if sync and not args.once
                    else sync.reader
                    if sync
                    else None,
                )
                if config.sender_source
                else None
            )
            if sync and args.retry_failed_sync:
                emit("sync_requeued", jobs=sync.state.retry_failed())
            if sender and args.retry_failed_sources:
                emit("sources_requeued", jobs=sender.rules.retry_failed())
            source_worker = SourceWorker(sender) if sender and not args.once else None
            if source_worker:
                resources.callback(source_worker.close)
            if fixture:
                accepted = store.observe(fixture.observations)
                emit("fixture_imported", accepted=accepted, synthetic=True)
            emit(
                "ready",
                mode="apply_categories" if category_application else "dry_run",
                mailbox_collection="read_only_delta" if sync else "disabled",
                actor_rules="accepted_poc_indicators_and_human_compatibility"
                if config.known_mcp_marker_poc_enabled or config.gmail_api_agent_poc_enabled
                else "corroborated_poc_ai_and_human_label",
                known_mcp_marker_poc_enabled=config.known_mcp_marker_poc_enabled,
                gmail_api_agent_poc_enabled=config.gmail_api_agent_poc_enabled,
                receiving_scope="all_incoming_headers",
                category_writes=writes_enabled,
            )
            while True:
                if sync:
                    sync.run_cycle()
                    emit("sync_cycle_completed", **sync.state.summary())
                fast_poc = config.known_mcp_marker_poc_enabled or config.gmail_api_agent_poc_enabled
                if sender and args.once and not fast_poc:
                    sender.step()
                    emit("sender_sources", **sender.rules.summary())
                processed = run_once(store)
                if category_application:
                    # Each item is independently checked against its current live
                    # version/location. An unrelated folder failure cannot starve it.
                    for result in category_application.run_cycle():
                        emit("category_result", **result)
                    emit("category_cycle_completed", **category_application.summary())
                emit("cycle_completed", processed=processed, **store.summary())
                if source_worker:
                    emit("sender_worker", **source_worker.tick())
                    emit("sender_sources", **source_worker.collector.rules.summary())
                elif sender and fast_poc:
                    # Header/transport POC verdicts do not wait behind the slower
                    # analytical audit endpoint. Its evidence is still collected
                    # and reassessed in the next cycle; it can expose conflicts.
                    sender.step()
                    emit("sender_sources", **sender.rules.summary())
                if args.once:
                    return (
                        1
                        if (
                            sync
                            and (
                                sync.state.summary()["sync_health"] == "degraded"
                                or sync.state.summary()["sync_retry_waiting"]
                            )
                        )
                        or (sender and sender.rules.summary()["source_blocked"])
                        or (
                            category_application
                            and category_application.summary()["category_health"] != "current"
                        )
                        else 0
                    )
                if not sync or not sync.state.summary()["sync_ready_jobs"]:
                    time.sleep(config.poll_seconds)
    except KeyboardInterrupt:
        emit("stopped", reason="operator_interrupt", category_writes=writes_enabled)
        return 0
    except OutlookError as error:
        emit("error", code=error.code, category_writes=writes_enabled)
        return 1
    except (InputError, ValidationError, OSError, ValueError, sqlite3.Error):
        emit("error", code="invalid_input_or_runtime_unavailable", category_writes=writes_enabled)
        return 1
    except Exception:
        # Last-resort process boundary: never print third-party exception text,
        # tokens, URLs or source data, and never turn a failure into a verdict.
        emit("error", code="unexpected_runtime_failure", category_writes=writes_enabled)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
