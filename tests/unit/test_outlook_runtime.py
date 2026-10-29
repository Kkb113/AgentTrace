"""Standalone runtime contracts, crash consistency and annotation admission boundaries."""

from __future__ import annotations

import json
import os
import runpy
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from agenttrace_outlook.cli import main
from agenttrace_outlook.config import CategoryMapping, RuntimeConfig, read_config
from agenttrace_outlook.contracts import Decision, FixtureBatch, Observation, Scope
from agenttrace_outlook.eligibility import UNKNOWN_RULE, require_annotation_eligible
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.reader import MailReader, certificate_reader
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.state import StateStore

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
SCOPE = Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=2))


def config(path: Path, **changes: object) -> RuntimeConfig:
    return RuntimeConfig.model_validate({"scope": SCOPE, "state_directory": str(path), **changes})


def observation(**changes: object) -> Observation:
    return Observation.model_validate(
        {
            "scope": SCOPE,
            "message_id": "synthetic-message",
            "source_version": "v1",
            "observed_at": NOW,
            "received_at": NOW - timedelta(seconds=1),
            "inspection_complete": True,
            "source_digest": "a" * 64,
            **changes,
        }
    )


def decision(**changes: object) -> Decision:
    return Decision.model_validate(
        {
            "scope": SCOPE,
            "message_id": "synthetic-message",
            "source_version": "v1",
            "category": "Unknown",
            "rule_version": UNKNOWN_RULE,
            "basis": "production",
            "qualification": "not_required",
            "reason_codes": ("sender_rules_not_qualified",),
            "decided_at": NOW,
            "expires_at": NOW + timedelta(days=30),
            **changes,
        }
    )


def write_config(tmp_path: Path, **changes: object) -> Path:
    path = tmp_path / "config.json"
    path.write_text(config(tmp_path / "private", **changes).model_dump_json(), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "changes",
    [
        {"unknown_option": True},
        {"demo_heuristic": True},
        {"poll_seconds": True},
        {"state_directory": "relative"},
        {"state_directory": "//server/share"},
        {"production_positive_rules": ("demo",)},
        {"poll_seconds": 60, "lease_seconds": 30},
        {"raw_retention_days": 30},
        {"data_boundary": "customer_data"},
        {"mode": "send"},
    ],
)
def test_configuration_is_closed(tmp_path: Path, changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        config(tmp_path, **changes)


def test_input_and_category_contracts(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        CategoryMapping(human_color="preset0")
    with pytest.raises(ValidationError):
        observation(received_at=NOW + timedelta(seconds=1))
    with pytest.raises(ValidationError):
        observation(observed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        observation(body="not an allowed field")
    with pytest.raises(ValidationError):
        decision(category="Human")
    with pytest.raises(ValidationError):
        decision(category="AI Agent", qualification="qualified")
    with pytest.raises(ValidationError):
        FixtureBatch(synthetic=False, observations=())
    path = tmp_path / "bad.json"
    path.write_text('{"secret":"private-input","secret":"duplicate"}')
    with pytest.raises(OutlookError, match="invalid_configuration") as caught:
        read_config(path)
    assert "private-input" not in str(caught.value)


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"basis": "experimental"}, "experimental_decision_rejected"),
        (
            {
                "category": "AI Agent",
                "qualification": "qualified",
                "evidence_refs": ("fake-evidence",),
            },
            "rule_not_enrolled_or_qualified",
        ),
        (
            {
                "category": "Human",
                "qualification": "qualified",
                "evidence_refs": ("fake-evidence",),
            },
            "rule_not_enrolled_or_qualified",
        ),
        ({"rule_version": "demo/v1"}, "rule_not_enrolled_or_qualified"),
        ({"decided_at": NOW + timedelta(seconds=1)}, "decision_outside_validity"),
        ({"expires_at": NOW}, "invalid"),
        (
            {"scope": Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=3))},
            "decision_scope_mismatch",
        ),
    ],
)
def test_annotation_admission(changes: dict[str, object], code: str) -> None:
    if code == "invalid":
        with pytest.raises(ValidationError):
            decision(**changes)
    else:
        with pytest.raises(OutlookError, match=code):
            require_annotation_eligible(decision(**changes), SCOPE, NOW)


def test_atomic_idempotent_versioned_processing(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    with StateStore(cfg, clock=lambda: NOW) as store:
        assert store.observe([observation()]) == 1
        assert store.observe([observation(observed_at=NOW + timedelta(seconds=1))]) == 0
        assert run_once(store) == 1
        assert run_once(store) == 0
        assert store.db.execute("SELECT status,category FROM outbox").fetchone()[:] == (
            "preview",
            "Unknown",
        )
        assert (
            store.observe(
                [observation(source_version="v2", observed_at=NOW + timedelta(seconds=2))]
            )
            == 1
        )
        assert store.db.execute("SELECT status FROM outbox").fetchone()[0] == "superseded"
        assert run_once(store) == 1
        assert [r[0] for r in store.db.execute("SELECT version FROM decisions")] == [1, 2]
        activation = store.summary()["activation_utc"]
        generation = store.lease.generation
    with StateStore(cfg, clock=lambda: NOW) as store:
        assert store.lease.generation == generation + 1
        assert store.summary()["activation_utc"] == activation
        assert run_once(store) == 0
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_invalid_batch_and_stale_decisions(tmp_path: Path) -> None:
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        for limit in (-1, 0, 101, True):
            with pytest.raises(OutlookError, match="invalid_work_batch_size"):
                store.pending(limit)
        store.observe([observation()])
        item_id = store.pending(1)[0][0]
        with pytest.raises(OutlookError, match="decision_retention_exceeds_baseline"):
            store.record_decision(item_id, decision(expires_at=NOW + timedelta(days=31)))
        with pytest.raises(OutlookError, match="stale_or_mismatched_decision"):
            store.record_decision(item_id, decision(source_version="different"))
        store.observe([observation(source_version="new")])
        with pytest.raises(OutlookError, match="stale_or_mismatched_decision"):
            store.record_decision(item_id, decision())
        assert store.summary()["decisions"] == 0


@pytest.mark.parametrize("checkpoint", ["migration", "decision_committed"])
def test_process_crashes_at_schema_and_decision_boundaries(tmp_path: Path, checkpoint: str) -> None:
    path = write_config(tmp_path)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        FixtureBatch(synthetic=True, observations=(observation(),)).model_dump_json()
    )
    script = """
import os, sys
from pathlib import Path
from datetime import datetime, UTC
from agenttrace_outlook.config import read_config
from agenttrace_outlook.contracts import FixtureBatch
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.state import StateStore
class CrashMigration(StateStore):
    def _migrate_and_bind(self):
        with self.transaction() as db:
            db.execute("CREATE TABLE partial_migration (id INTEGER)")
            db.execute("PRAGMA user_version=1")
            os._exit(23)
cls=CrashMigration if sys.argv[3]=='migration' else StateStore
store=cls(read_config(Path(sys.argv[1])),clock=lambda:datetime(2026,10,29,12,tzinfo=UTC))
store.observe(FixtureBatch.model_validate_json(Path(sys.argv[2]).read_text()).observations)
run_once(store)
os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(fixture), checkpoint],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 23, result.stderr
    with StateStore(read_config(path), clock=lambda: NOW) as store:
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        if checkpoint == "migration":
            assert store.summary()["observations"] == 0
            store.observe([observation()])
            assert run_once(store) == 1
        else:
            assert run_once(store) == 0
            assert store.summary()["decisions"] == 1
            assert store.summary()["outbox_preview"] == 1


def test_boundary_gate_rejects_demo_imports_and_non_get(tmp_path: Path) -> None:
    namespace = runpy.run_path("scripts/check-outlook-boundaries.py")
    check = namespace["main"]
    check.__globals__["ROOT"] = tmp_path
    package = tmp_path / "src/agenttrace_outlook"
    package.mkdir(parents=True)
    sample = package / "reader.py"
    sample.write_text(
        'from agenttrace_feasibility.mail_monitor import main\ntransport.request("PATCH", "url")\n'
    )
    assert check() == 1
    sample.write_text('transport.request("GET", "url")\n')
    assert check() == 0


def test_cli_interrupt_closes_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_config(tmp_path)

    def interrupt(_: int) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("agenttrace_outlook.cli.time.sleep", interrupt)
    assert main(["--config", str(path)]) == 0
    with StateStore(read_config(path)) as store:
        assert store.summary()["decisions"] == 0


def test_import_conflict_rolls_back_entire_batch(tmp_path: Path) -> None:
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        store.observe([observation()])
        with pytest.raises(OutlookError, match="observation_version_conflict"):
            store.observe([observation(message_id="new"), observation(source_digest="b" * 64)])
        assert store.summary()["observations"] == 1
        with pytest.raises(OutlookError, match="observation_scope_mismatch"):
            store.observe([observation(scope=Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=3)))])
        with pytest.raises(OutlookError, match="stale_observation"):
            store.observe(
                [observation(source_version="older", observed_at=NOW - timedelta(seconds=1))]
            )


def test_decision_and_outbox_roll_back_together(tmp_path: Path) -> None:
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        store.observe([observation()])
        store.db.execute(
            "CREATE TEMP TRIGGER simulate_disk_error BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'private driver details'); END"
        )
        with pytest.raises(OutlookError, match="state_transaction_failed"):
            run_once(store)
        assert store.summary()["decisions"] == 0
        assert store.summary()["outbox"] == 0
        assert store.summary()["work_pending"] == 1
        store.db.execute("DROP TRIGGER simulate_disk_error")
        assert run_once(store) == 1


def test_sqlite_disk_full_is_safe_and_retryable(tmp_path: Path) -> None:
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        pages = store.db.execute("PRAGMA page_count").fetchone()[0]
        store.db.execute("PRAGMA max_page_count=" + str(pages))
        batch = [observation(message_id="synthetic-" + str(i)) for i in range(100)]
        with pytest.raises(OutlookError, match="state_transaction_failed"):
            store.observe(batch)
        assert store.summary()["observations"] == 0
        assert store.summary()["work_pending"] == 0
        store.db.execute("PRAGMA max_page_count=10000")
        assert store.observe(batch) == 100
        assert run_once(store) == 50
        assert run_once(store) == 50
        assert store.summary()["outbox_preview"] == 100


@pytest.mark.parametrize("observed_at", [NOW - timedelta(days=7), NOW + timedelta(minutes=6)])
def test_invalid_observation_windows_are_rejected(tmp_path: Path, observed_at: datetime) -> None:
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        with pytest.raises(OutlookError, match="observation_outside_validity"):
            store.observe([observation(observed_at=observed_at, received_at=observed_at)])
        assert store.summary()["decisions"] == 0


def test_hard_linked_database_is_rejected(tmp_path: Path) -> None:
    with StateStore(config(tmp_path)):
        pass
    os.link(tmp_path / "runtime.sqlite3", tmp_path / "database-alias")
    with pytest.raises(OutlookError, match="state_path_alias_rejected"):
        StateStore(config(tmp_path))


def test_retry_dead_letter_and_expiry(tmp_path: Path) -> None:
    current = NOW
    with StateStore(config(tmp_path, max_attempts=2), clock=lambda: current) as store:
        store.observe([observation()])
        item_id = store.pending(1)[0][0]
        store.fail_work(item_id, "processing_failed")
        assert store.pending(1) == []
        current += timedelta(seconds=3)
        assert len(store.pending(1)) == 1
        store.fail_work(item_id, "processing_failed")
        assert store.summary()["work_dead_letter"] == 1
        with pytest.raises(OutlookError, match="unsafe_work_error_code"):
            store.fail_work(item_id, "private text")
        store.observe([observation(source_version="v2")])
        current = NOW + timedelta(days=8)
        # A long outage first loses its lease; the next process resumes safely.
        with pytest.raises(OutlookError, match="lease_lost"):
            run_once(store)
    with StateStore(config(tmp_path), clock=lambda: current) as store:
        assert run_once(store) == 0
        assert store.summary()["work_dead_letter"] == 2
        assert store.summary()["decisions"] == 0


def test_fences_and_multiple_instances(tmp_path: Path) -> None:
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        with pytest.raises(OutlookError, match="runtime_already_running"):
            StateStore(config(tmp_path))
        with pytest.raises(OutlookError, match="lease_lost"):
            with store.transaction(lease=replace(store.lease, generation=0)):
                pytest.fail("stale writer entered transaction")


@pytest.mark.parametrize(
    "fault,code",
    [
        ("future", "unsupported_state_schema"),
        ("drift", "state_schema_modified"),
        ("scope", "state_scope_or_schema_mismatch"),
        ("corrupt", "state_initialization_failed"),
    ],
)
def test_migrations_reject_unknown_state(tmp_path: Path, fault: str, code: str) -> None:
    cfg = config(tmp_path)
    with StateStore(cfg):
        pass
    path = tmp_path / "runtime.sqlite3"
    if fault == "corrupt":
        path.write_bytes(b"invalid synthetic database")
    else:
        with sqlite3.connect(path) as db:
            if fault == "future":
                db.execute("PRAGMA user_version=999")
            elif fault == "drift":
                db.execute("ALTER TABLE work ADD COLUMN unexpected TEXT")
            else:
                db.execute("UPDATE metadata SET value='wrong' WHERE key='scope'")
    with pytest.raises(OutlookError, match=code):
        StateStore(cfg)


def test_crash_before_and_after_commit_and_process_exclusion(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        FixtureBatch(synthetic=True, observations=(observation(),)).model_dump_json()
    )
    script = """
import os, sys
from pathlib import Path
from agenttrace_outlook.config import read_config
from agenttrace_outlook.contracts import FixtureBatch
from agenttrace_outlook.state import StateStore
from datetime import datetime, UTC
store=StateStore(read_config(Path(sys.argv[1])),clock=lambda:datetime(2026,10,29,12,tzinfo=UTC))
store.observe(FixtureBatch.model_validate_json(Path(sys.argv[2]).read_text()).observations)
store.db.execute("BEGIN IMMEDIATE")
store.db.execute("UPDATE work SET status='completed'")
print('locked',flush=True)
sys.stdin.readline()
os._exit(19)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(path), str(fixture)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        blocked = subprocess.run(
            [sys.executable, "scripts/monitor-outlook-mail.py", "--config", str(path), "--once"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert blocked.returncode == 1
        assert "runtime_already_running" in blocked.stdout
        proc.communicate("exit\n", timeout=20)
        assert proc.returncode == 19
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=20)
    with StateStore(read_config(path), clock=lambda: NOW) as store:
        assert store.summary()["work_pending"] == 1
        assert run_once(store) == 1
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_cli_dry_run_is_standalone_and_restartable(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    path = write_config(tmp_path)
    fixture = tmp_path / "fixture.json"
    fixture.write_text(
        FixtureBatch(
            synthetic=True, observations=(observation(observed_at=now, received_at=now),)
        ).model_dump_json()
    )
    command = [
        sys.executable,
        "scripts/monitor-outlook-mail.py",
        "--config",
        str(path),
        "--fixture",
        str(fixture),
        "--once",
    ]
    for count in (1, 0):
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert events[-1]["processed"] == count
        assert events[-1]["decisions"] == 1
        assert '"category_writes": false' in result.stdout
        assert "synthetic-message" not in result.stdout
        assert "Traceback" not in result.stderr


def test_documented_prepare_and_run_command(tmp_path: Path) -> None:
    directory = tmp_path / "demo"
    prepared = subprocess.run(
        [sys.executable, "scripts/prepare-outlook-dry-run.py", "--directory", str(directory)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert prepared.returncode == 0, prepared.stderr
    result = subprocess.run(
        [
            sys.executable,
            "scripts/monitor-outlook-mail.py",
            "--config",
            str(directory / "runtime.json"),
            "--fixture",
            str(directory / "observations.json"),
            "--once",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])["outbox_preview"] == 1
    assert not (directory / "state/runtime.sqlite3-wal").exists()


def test_apply_and_invalid_inputs_have_no_side_effects(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*args: object, **kwargs: object) -> None:
        pytest.fail("foundation must not open a network connection")

    monkeypatch.setattr("socket.socket.connect", no_network)
    path = write_config(tmp_path)
    assert main(["--config", str(path), "--check"]) == 0
    assert not (tmp_path / "private").exists()
    assert main(["--config", str(path), "--apply-categories"]) == 1
    assert not (tmp_path / "private").exists()
    assert main(["--config", str(path), "--once"]) == 0
    path = write_config(tmp_path, mode="apply_categories")
    assert main(["--config", str(path), "--check"]) == 1
    assert main(["--config", str(path), "--check", "--dry-run"]) == 0
    path.write_text('{"sensitive":"private-secret"}')
    assert main(["--config", str(path), "--once"]) == 1
    assert "private-secret" not in capsys.readouterr().out


def test_disk_path_failure_and_apply_store_guard(tmp_path: Path) -> None:
    with pytest.raises(OutlookError, match="category_application_not_enabled"):
        StateStore(config(tmp_path / "unused", mode="apply_categories"))
    assert not (tmp_path / "unused").exists()
    (tmp_path / "not-directory").write_text("synthetic")
    with pytest.raises(OutlookError, match="state_initialization_failed"):
        StateStore(config(tmp_path / "not-directory"))


def test_read_adapter_is_fixed_get_metadata_and_encodes_ids(tmp_path: Path) -> None:
    calls = []

    class Transport:
        def request(self, method: str, url: str, *, headers: dict[str, str]) -> dict[str, object]:
            calls.append((method, url, headers))
            return {"id": "synthetic"}

    reader = MailReader(config(tmp_path), Transport())
    assert reader.message_metadata("../sendMail?x=1")["id"] == "synthetic"
    method, url, headers = calls[0]
    assert method == "GET" and "/messages/..%2FsendMail%3Fx%3D1?" in url
    assert "/users/" + str(SCOPE.mailbox_id) + "/messages/" in url
    assert "body" not in url and "subject" not in url
    assert headers == {"Prefer": 'IdType="ImmutableId"'}
    with pytest.raises(OutlookError, match="invalid_message_reference"):
        reader.message_metadata("")
    with pytest.raises(OutlookError, match="reader_identity_not_configured"):
        certificate_reader(config(tmp_path))


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation requires extra privileges")
def test_local_path_aliases_are_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(OutlookError, match="state_path_alias_rejected"):
        StateStore(config(link))
