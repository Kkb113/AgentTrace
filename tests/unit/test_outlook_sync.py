"""Graph sync contract, transactional checkpoints, recovery and scale validation."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest

from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.contracts import IngestionError
from agenttrace_outlook.cli import main
from agenttrace_outlook.config import ReaderIdentity, RuntimeConfig
from agenttrace_outlook.contracts import Observation, Scope
from agenttrace_outlook.errors import OutlookError, SourceError
from agenttrace_outlook.reader import MailReader
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.state import BASE_DIGEST, BASE_SCHEMA, StateStore
from agenttrace_outlook.synchronizer import Synchronizer

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
SCOPE = Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=2))


def config(path: Path, **changes: Any) -> RuntimeConfig:
    return RuntimeConfig(
        scope=SCOPE,
        state_directory=str(path),
        sync_enabled=True,
        reader_identity=ReaderIdentity(client_id=UUID(int=3), certificate_thumbprint="a" * 40),
        **changes,
    )


def folder(
    identity: str, parent: str = "mail-root", children: int = 0, hidden: bool = False
) -> dict:
    return {
        "id": identity,
        "parentFolderId": parent,
        "childFolderCount": children,
        "isHidden": hidden,
    }


def detail(identity: str, parent: str = "inbox", **changes: Any) -> dict:
    return {
        "id": identity,
        "parentFolderId": parent,
        "changeKey": "provider-1",
        "receivedDateTime": NOW.isoformat(),
        "sentDateTime": NOW.isoformat(),
        "isDraft": False,
        "subject": "AgentTrace synthetic test: invented",
        "internetMessageId": "<fictional@example.invalid>",
        "internetMessageHeaders": [{"name": "X-Test", "value": "fictional"}],
        "categories": [],
        **changes,
    }


class Graph:
    """Deterministic contract server. Current-message GET defeats stale delta ordering."""

    def __init__(self) -> None:
        self.folders = [
            folder("inbox"),
            folder("junk"),
            folder("rules"),
            *(folder(n) for n in ("drafts", "sentitems", "outbox", "deleteditems")),
        ]
        self.children: dict[str, list[dict]] = {}
        self.messages: dict[str, dict] = {}
        self.pages: dict[str, list[list[dict]]] = {}
        self.calls: list[tuple[str, str]] = []
        self.failures: dict[str, IngestionError] = {}
        self.folder_page_size = 1000

    def request(self, method: str, url: str, *, headers: dict[str, str]) -> dict:
        assert method == "GET"
        assert 'IdType="ImmutableId"' in headers["Prefer"]
        self.calls.append((method, url))
        path, query = urlsplit(url).path, parse_qs(urlsplit(url).query)
        for match, error in self.failures.items():
            if match in path:
                raise error
        tail = path.split("/users/")[1].split("/", 1)[1]
        base = url.split("?", 1)[0]
        if tail.startswith("messages/"):
            identity = tail.split("/", 1)[1]
            if identity not in self.messages:
                raise IngestionError("source_item_not_found")
            return dict(self.messages[identity])
        if tail.startswith("mailFolders/") and tail.count("/") == 1:
            return {"id": tail.split("/")[1]}
        if tail == "mailFolders" or tail.endswith("/childFolders"):
            target = "root" if tail == "mailFolders" else tail.split("/")[1]
            values = self.folders if target == "root" else self.children[target]
            index = int(query.get("$skiptoken", ["0"])[0])
            response = {"value": values[index : index + self.folder_page_size]}
            if index + self.folder_page_size < len(values):
                response["@odata.nextLink"] = (
                    base + "?$skiptoken=" + str(index + self.folder_page_size)
                )
            return response
        target = tail.split("/")[1]
        pages = self.pages.get(target, [[]])
        index = int(query.get("$skiptoken", ["0"])[0])
        if "$deltatoken" in query:
            values, link = [], "@odata.deltaLink"
            token = "$deltatoken=settled"
        elif index + 1 < len(pages):
            values, link = pages[index], "@odata.nextLink"
            token = "$skiptoken=" + str(index + 1)
        else:
            values, link = pages[index], "@odata.deltaLink"
            token = "$deltatoken=settled"
        return {"value": values, link: base + "?" + token}


def settle(sync: Synchronizer, cycles: int = 20) -> None:
    for _ in range(cycles):
        sync.run_cycle()
        run_once(sync.store)
        if sync.state.next_job() is None:
            return
    pytest.fail("sync failed to drain its due work")


def requeue(sync: Synchronizer, identity: str) -> None:
    with sync.store.transaction(lease=sync.store.lease) as db:
        sync.state.hydrate(db, identity)


def test_discovery_activation_body_exclusion_and_restart(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages = {
        "new": detail("new"),
        "old": detail("old", receivedDateTime=(NOW - timedelta(days=1)).isoformat()),
        "ordinary": detail("ordinary", subject="non-synthetic private subject"),
    }
    graph.pages["inbox"] = [[{"id": k} for k in graph.messages]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync)
        assert store.summary()["decisions"] == 1
        assert sync.state.summary()["sync_items"] == 3
        assert sync.state.summary()["folders_receiving"] == 3
        assert sync.state.summary()["folders_excluded"] == 4
        assert [
            r[0] for r in store.db.execute("SELECT status FROM sync_items ORDER BY message_id")
        ] == ["eligible", "history", "non_synthetic"]
        assert (
            "private subject" not in store.db.execute("SELECT payload FROM snapshots").fetchone()[0]
        )
        assert not any("body" in url or "$filter" in url for _, url in graph.calls)
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        settle(Synchronizer(store, MailReader(store.config, graph)))
        assert store.summary()["decisions"] == 1


def test_move_old_tombstone_category_echo_and_real_evidence_change(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages["one"] = detail("one")
    graph.pages["inbox"] = [[{"id": "one"}]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync)
        graph.messages["one"].update(
            parentFolderId="rules",
            changeKey="provider-2",
            categories=["Unknown", "unrelated"],
            isRead=True,
        )
        requeue(sync, "one")
        settle(sync)
        assert store.summary()["decisions"] == 1
        assert store.db.execute("SELECT folder_id FROM sync_items").fetchone()[0] == "rules"
        # Late deletion from the old folder must resolve the current received copy.
        job = dict(store.db.execute("SELECT * FROM sync_jobs WHERE key='delta:inbox'").fetchone())
        job["cursor"] = None
        graph.pages["inbox"] = [[{"id": "one", "@removed": {"reason": "deleted"}}]]
        sync.page(job)
        settle(sync)
        assert store.summary()["decisions"] == 1
        graph.messages["one"]["internetMessageHeaders"] = [
            {"name": "X-Test", "value": "changed evidence"}
        ]
        requeue(sync, "one")
        settle(sync)
        assert store.summary()["decisions"] == 2
        assert store.summary()["outbox_preview"] == 1
        assert store.summary()["outbox_superseded"] == 1


def test_no_ten_thousand_message_cap_and_page_budget_is_durable(tmp_path: Path) -> None:
    graph = Graph()
    count = 10023
    # The whole population is history: exercise every ID/checkpoint without
    # fabricating an accuracy dataset or storing message text.
    graph.messages = {
        "m" + str(i): detail("m" + str(i), receivedDateTime=(NOW - timedelta(days=1)).isoformat())
        for i in range(count)
    }
    values = [{"id": identity} for identity in graph.messages]
    graph.pages["inbox"] = [values[i : i + 100] for i in range(0, count, 100)]
    cfg = config(tmp_path, sync_operations_per_cycle=100)
    with StateStore(cfg, clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(cfg, graph))
        for _ in range(6):
            sync.run_cycle()
        partial = sync.state.summary()["sync_items"]
        assert 0 < partial < count
    with StateStore(cfg, clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(cfg, graph))
        settle(sync, cycles=130)
        assert sync.state.summary()["sync_items"] == count
        assert sync.state.summary()["sync_pending_items"] == 0
        assert store.summary()["decisions"] == 0


def test_discovery_new_nested_folders_and_deleted_folder(tmp_path: Path) -> None:
    current = NOW
    graph = Graph()
    with StateStore(config(tmp_path), clock=lambda: current) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync)
        graph.folders.append(folder("parent", children=1))
        graph.children["parent"] = [folder("child", parent="parent")]
        current += timedelta(seconds=301)
        # Simulate the scheduler staying alive, renewing its lease each poll.
        store.db.execute("UPDATE lease SET expires=?", (current.timestamp() + 120,))
        settle(sync)
        assert sync.state.summary()["folders_receiving"] == 5
        graph.folders = [f for f in graph.folders if f["id"] != "parent"]
        current += timedelta(seconds=301)
        store.db.execute("UPDATE lease SET expires=?", (current.timestamp() + 120,))
        settle(sync)
        assert sync.state.summary()["folders_receiving"] == 3


@pytest.mark.parametrize(
    "code,retryable,status",
    [
        ("source_access_denied", False, "blocked"),
        ("source_network_unavailable", True, "due"),
        ("source_throttled", True, "due"),
    ],
)
def test_failures_are_durable_and_never_imply_human(
    tmp_path: Path, code: str, retryable: bool, status: str
) -> None:
    graph = Graph()
    graph.failures["/mailFolders/drafts"] = IngestionError(
        code, retryable=retryable, retry_after=90
    )
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        sync.run_cycle()
        job = store.db.execute("SELECT * FROM sync_jobs WHERE key='system:drafts'").fetchone()
        assert job["status"] == status
        assert job["due"] >= NOW.timestamp() + 90
        assert store.summary()["decisions"] == 0
        assert sync.state.summary()["folders_receiving"] == 0
        assert sync.state.next_job() is None


def test_retry_exhaustion_requires_explicit_retry(tmp_path: Path) -> None:
    current = NOW
    graph = Graph()
    graph.failures["/mailFolders/drafts"] = IngestionError(
        "source_throttled", retryable=True, retry_after=1
    )
    cfg = config(tmp_path, max_attempts=2)
    with StateStore(cfg, clock=lambda: current) as store:
        sync = Synchronizer(store, MailReader(cfg, graph))
        sync.run_cycle()
        current += timedelta(seconds=10)
        sync.run_cycle()
        assert sync.state.summary()["sync_jobs_dead_letter"] == 1
        del graph.failures["/mailFolders/drafts"]
        assert sync.state.retry_failed() == 1
        settle(sync)
        assert sync.state.summary()["folders_receiving"] == 3
        assert sync.state.summary()["sync_gaps"] == 0
        assert (
            store.db.execute("SELECT count(*) FROM sync_gaps WHERE resolved=1").fetchone()[0] == 1
        )


def test_cursor_expiry_reconciles_and_reports_unobserved_window(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages["gone"] = detail("gone")
    graph.pages["inbox"] = [[{"id": "gone"}]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync)
        job = dict(store.db.execute("SELECT * FROM sync_jobs WHERE key='delta:inbox'").fetchone())
        sync.state.fail(job, SourceError("source_cursor_expired"), 0)
        graph.pages["inbox"] = [[]]
        del graph.messages["gone"]
        settle(sync)
        assert sync.state.summary()["sync_gaps"] == 2
        assert (
            store.db.execute("SELECT status FROM sync_items").fetchone()[0]
            == "gone_or_inaccessible"
        )
        assert store.summary()["outbox_preview"] == 0


def test_checkpoint_rollback_and_stale_response_rejection(tmp_path: Path) -> None:
    graph = Graph()
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        for _ in range(4):
            system_job = sync.state.next_job()
            assert system_job and system_job["kind"] == "system"
            sync.system(system_job)
        sync.state.start_discovery()
        job = sync.state.next_job()
        assert job and job["kind"] == "discover"
        store.db.execute(
            "CREATE TEMP TRIGGER abort_checkpoint BEFORE UPDATE OF generation ON sync_jobs WHEN OLD.key='discover:root' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(OutlookError, match="state_transaction_failed"):
            sync.page(job)
        assert store.db.execute("SELECT count(*) FROM folders").fetchone()[0] == 0
        store.db.execute("DROP TRIGGER abort_checkpoint")
        sync.page(job)
        with pytest.raises(OutlookError, match="stale_sync_page"):
            sync.page(job)
        assert store.db.execute("SELECT count(*) FROM folders").fetchone()[0] == 7


def test_v1_additive_migration_preserves_activation_and_rejects_drift(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    with sqlite3.connect(tmp_path / "runtime.sqlite3") as db:
        for sql in BASE_SCHEMA:
            db.execute(sql)
        db.execute("PRAGMA user_version=1")
        db.executemany(
            "INSERT INTO metadata VALUES (?,?)",
            [
                ("schema_digest", BASE_DIGEST),
                ("scope", SCOPE.model_dump_json()),
                ("activation_utc", NOW.isoformat()),
            ],
        )
        item = Observation(
            scope=SCOPE,
            message_id="legacy",
            source_version="v1",
            observed_at=NOW,
            received_at=NOW,
            inspection_complete=True,
            source_digest="a" * 64,
        )
        db.execute(
            "INSERT INTO observations VALUES (1,'legacy','v1',?,?,?)",
            ("a" * 64, item.model_dump_json(), (NOW + timedelta(days=7)).timestamp()),
        )
        db.execute("INSERT INTO messages VALUES ('legacy',1,0)")
        db.execute("INSERT INTO work(observation_id,status) VALUES (1,'pending')")
    with StateStore(cfg, clock=lambda: NOW) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert store.summary()["activation_utc"] == NOW.isoformat()
        sync = Synchronizer(store, MailReader(cfg, Graph()))
        assert sync.state.cutoff == NOW
        assert run_once(store) == 1
        assert store.summary()["decisions"] == 1


@pytest.mark.parametrize(
    "change",
    [
        "https://evil.invalid/v1.0",
        "/users/other/",
        "/messages/delta?%24expand=body",
        "/messages/delta?%24select=body",
    ],
)
def test_cursor_scope_and_field_exfiltration_are_rejected(tmp_path: Path, change: str) -> None:
    graph = Graph()
    reader = MailReader(config(tmp_path), graph)
    good = reader.collection_url("delta", "inbox")
    if change.startswith("https"):
        bad = good.replace("https://graph.microsoft.com/v1.0", change)
    elif change.startswith("/users"):
        bad = good.replace("/users/" + str(SCOPE.mailbox_id) + "/", change)
    else:
        bad = good.split("/messages/delta")[0] + change
    with pytest.raises(SourceError, match="unsafe_source_cursor"):
        reader.validate_cursor(bad, "delta", "inbox")
    assert graph.calls == []


def test_backfill_boundary_is_explicit_and_cannot_change_on_restart(tmp_path: Path) -> None:
    with StateStore(
        config(tmp_path, backfill_since=NOW - timedelta(hours=1)), clock=lambda: NOW
    ) as store:
        Synchronizer(store, MailReader(store.config, Graph()))
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        with pytest.raises(OutlookError, match="sync_boundary_changed"):
            Synchronizer(store, MailReader(store.config, Graph()))


@pytest.mark.parametrize("stage", ["discover", "delta", "detail"])
@pytest.mark.parametrize("position", ["before_commit", "after_commit"])
def test_process_crash_at_each_sync_checkpoint(tmp_path: Path, stage: str, position: str) -> None:
    path = tmp_path / "runtime.json"
    path.write_text(config(tmp_path / "state").model_dump_json(), encoding="utf-8")
    script = """
import os,runpy,sys
from pathlib import Path
from agenttrace_outlook.config import read_config
from agenttrace_outlook.state import StateStore
from agenttrace_outlook.reader import MailReader
from agenttrace_outlook.synchronizer import Synchronizer
test=runpy.run_path('tests/unit/test_outlook_sync.py')
graph=test['Graph'](); graph.messages['one']=test['detail']('one'); graph.pages['inbox']=[[{'id':'one'}]]
store=StateStore(read_config(Path(sys.argv[1])),clock=lambda:test['NOW'])
sync=Synchronizer(store,MailReader(store.config,graph))
for _ in range(4): sync.system(sync.state.next_job())
sync.state.start_discovery()
root=sync.state.next_job()
if sys.argv[2]!='discover': sync.page(root)
if sys.argv[2]=='detail':
    sync.page(dict(store.db.execute("SELECT * FROM sync_jobs WHERE key='delta:inbox'").fetchone()))
key={'discover':'discover:root','delta':'delta:inbox','detail':'detail:one'}[sys.argv[2]]
job=dict(store.db.execute('SELECT * FROM sync_jobs WHERE key=?',(key,)).fetchone())
original=sync.state.checkpoint
def crash(db,job,**kwargs):
    if sys.argv[3]=='before_commit': os._exit(31)
    original(db,job,**kwargs)
sync.state.checkpoint=crash
if sys.argv[2]=='detail': sync.detail(job)
else: sync.page(job)
os._exit(31)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), stage, position],
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 31, result.stderr
    cfg = config(tmp_path / "state")
    graph = Graph()
    graph.messages["one"] = detail("one")
    graph.pages["inbox"] = [[{"id": "one"}]]
    with StateStore(cfg, clock=lambda: NOW) as store:
        if stage == "detail":
            assert store.summary()["observations"] == (0 if position == "before_commit" else 1)
        elif stage == "delta":
            count = store.db.execute("SELECT count(*) FROM sync_items").fetchone()[0]
            assert count == (0 if position == "before_commit" else 1)
        else:
            count = store.db.execute("SELECT count(*) FROM folders").fetchone()[0]
            assert count == (0 if position == "before_commit" else 7)
        settle(Synchronizer(store, MailReader(cfg, graph)))
        assert store.summary()["decisions"] == 1
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_incomplete_headers_and_current_deleted_copy_are_explicit(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages["one"] = detail("one", internetMessageHeaders=None)
    graph.pages["inbox"] = [[{"id": "one"}]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync)
        payload = json.loads(store.db.execute("SELECT payload FROM observations").fetchone()[0])
        assert payload["inspection_complete"] is False
        assert (
            json.loads(store.db.execute("SELECT payload FROM decisions").fetchone()[0])["category"]
            == "Unknown"
        )
        del graph.messages["one"]
        requeue(sync, "one")
        settle(sync)
        assert sync.state.summary()["sync_gaps"] == 1
        assert store.summary()["outbox_preview"] == 0


def test_long_retry_after_is_blocked_instead_of_retrying_early(tmp_path: Path) -> None:
    graph = Graph()
    graph.failures["/mailFolders/drafts"] = IngestionError(
        "source_throttled", retryable=True, retry_after=3600
    )
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        sync.run_cycle()
        assert (
            store.db.execute("SELECT error FROM sync_jobs WHERE key='system:drafts'").fetchone()[0]
            == "retry_after_requires_operator"
        )
        assert sync.state.summary()["sync_jobs_blocked"] == 1


def test_folder_pagination_and_fairness_under_message_backlog(tmp_path: Path) -> None:
    graph = Graph()
    graph.folder_page_size = 2
    graph.messages = {"m" + str(i): detail("m" + str(i)) for i in range(100)}
    graph.pages["inbox"] = [[{"id": identity} for identity in graph.messages], []]
    with StateStore(config(tmp_path, sync_operations_per_cycle=5), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync, cycles=60)
        assert sync.state.summary()["folders_receiving"] == 3
        assert store.summary()["decisions"] == 100
        urls = [url for _, url in graph.calls]
        junk = next(i for i, url in enumerate(urls) if "/junk/messages/delta" in url)
        second_inbox = next(
            i
            for i, url in enumerate(urls)
            if "/inbox/messages/delta" in url and "$skiptoken=1" in url
        )
        assert junk < second_inbox


def test_discovery_expired_cursor_and_removed_child_are_explicit(tmp_path: Path) -> None:
    graph = Graph()
    graph.folder_page_size = 2
    graph.folders.append(folder("parent", children=1))
    graph.children["parent"] = []
    with StateStore(config(tmp_path, sync_operations_per_cycle=1), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        for _ in range(5):
            sync.run_cycle()
        job = dict(store.db.execute("SELECT * FROM sync_jobs WHERE key='discover:root'").fetchone())
        assert job["cursor"]
        sync.state.fail(job, SourceError("source_cursor_expired"), 0)
        graph.failures["/parent/childFolders"] = IngestionError("source_item_not_found")
        settle(sync, cycles=40)
        assert sync.state.summary()["discovery_jobs_pending"] == 0
        assert sync.state.summary()["sync_gaps"] == 2


def test_historical_and_ordinary_headers_are_not_requested(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages["old"] = detail("old", receivedDateTime=(NOW - timedelta(days=1)).isoformat())
    graph.pages["inbox"] = [[{"id": "old"}]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        settle(Synchronizer(store, MailReader(store.config, graph)))
    reads = [url for _, url in graph.calls if "/messages/old?" in url]
    assert len(reads) == 1 and "internetMessageHeaders" not in reads[0]


def test_full_cli_sync_is_read_only_and_logs_no_private_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    graph = Graph()
    now = datetime.now(UTC)
    graph.messages["private-message-id"] = detail(
        "private-message-id", receivedDateTime=now.isoformat()
    )
    graph.pages["inbox"] = [[{"id": "private-message-id"}]]
    cfg = config(
        tmp_path / "state", backfill_since=now - timedelta(hours=1), sync_operations_per_cycle=100
    )
    path = tmp_path / "runtime.json"
    path.write_text(cfg.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        "agenttrace_outlook.cli.certificate_reader", lambda config: MailReader(config, graph)
    )
    assert main(["--config", str(path), "--once"]) == 0
    logs = capsys.readouterr().out
    assert "read_only_delta" in logs and "mailbox_sync_dry_run" in logs
    assert "private-message-id" not in logs and "invented" not in logs
    assert all(method == "GET" for method, _ in graph.calls)

    def private_failure(_: RuntimeConfig) -> None:
        raise RuntimeError("do-not-log-private-credential")

    monkeypatch.setattr("agenttrace_outlook.cli.certificate_reader", private_failure)
    assert main(["--config", str(path), "--check"]) == 0
    assert main(["--config", str(path), "--once"]) == 1
    assert "do-not-log" not in capsys.readouterr().out


def test_duplicate_internet_ids_do_not_merge_received_copies(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages = {"copy-a": detail("copy-a"), "copy-b": detail("copy-b")}
    graph.pages["inbox"] = [[{"id": identity} for identity in graph.messages]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        settle(Synchronizer(store, MailReader(store.config, graph)))
        assert store.summary()["decisions"] == 2
        assert store.summary()["observations"] == 2


def test_reused_certificate_auth_has_bounded_http_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class Application:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(
        "agenttrace_foundation.workload_identity.msal.ConfidentialClientApplication", Application
    )
    CertificateTokenProvider(
        str(SCOPE.tenant_id), str(UUID(int=3)), "a" * 40, tmp_path / "signer.ps1"
    )
    assert captured["timeout"] == 20
    assert captured["enable_pii_log"] is False


def test_newly_hidden_folder_reconciles_existing_preview(tmp_path: Path) -> None:
    graph = Graph()
    graph.messages["one"] = detail("one")
    graph.pages["inbox"] = [[{"id": "one"}]]
    current = NOW
    with StateStore(config(tmp_path), clock=lambda: current) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        settle(sync)
        assert store.summary()["outbox_preview"] == 1
        graph.folders[0]["isHidden"] = True
        current += timedelta(seconds=301)
        store.db.execute("UPDATE lease SET expires=?", (current.timestamp() + 120,))
        settle(sync)
        assert store.summary()["outbox_preview"] == 0
        assert (
            store.db.execute("SELECT status FROM sync_items WHERE message_id='one'").fetchone()[0]
            == "excluded"
        )
