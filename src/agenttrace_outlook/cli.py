"""Standalone foundation CLI: validated config, durable fixture replay and dry-run status."""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

from pydantic import ValidationError

from agenttrace_feasibility.validation import InputError, canonical_bytes, load_json

from .config import read_config
from .contracts import FixtureBatch
from .errors import OutlookError
from .runner import run_once
from .state import StateStore


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
        if args.check:
            emit(
                "configuration_valid",
                mode=config.mode,
                runtime_stage="foundation_only",
                category_writes=False,
            )
            return 0
        with StateStore(config) as store:
            if fixture:
                accepted = store.observe(fixture.observations)
                emit("fixture_imported", accepted=accepted, synthetic=True)
            emit(
                "ready",
                mode="dry_run",
                mailbox_collection="not_implemented_until_phase_2",
                actor_rules="not_qualified",
                category_writes=False,
            )
            while True:
                processed = run_once(store)
                emit("cycle_completed", processed=processed, **store.summary())
                if args.once:
                    return 0
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


if __name__ == "__main__":
    raise SystemExit(main())
