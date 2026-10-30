"""Slow analytical IO cannot block mail labels or mutate a closed/restarted store."""

from threading import Event, Thread
from types import SimpleNamespace

from agenttrace_outlook.category_application import CategoryApplication
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.source_worker import SourceWorker
from agenttrace_outlook.state import StateStore
from tests.unit.test_category_writer import setup


def test_slow_audit_does_not_block_classification_or_category_application(tmp_path):
    store, writer, server, _, _, _ = setup(tmp_path)
    started, release, finished = Event(), Event(), Event()
    calls = []

    def step():
        calls.append(1)
        started.set()
        release.wait(3)
        with store.transaction(lease=store.lease) as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('audit_test','completed')")
        finished.set()

    worker = SourceWorker(SimpleNamespace(step=step))
    try:
        worker.tick()
        assert started.wait(1)
        assert CategoryApplication(writer).run_cycle()[0]["status"] == "applied"
        assert server.item["categories"] == ["Personal", "Human"]
        assert worker.tick()["source_worker_busy"] is True
        assert len(calls) == 1
        assert not finished.is_set()
        release.set()
        assert finished.wait(1)
    finally:
        release.set()
        worker.close()
        store.close()


def test_late_network_result_cannot_write_after_shutdown_and_restart(tmp_path):
    store, _, _, clock, _, _ = setup(tmp_path)
    cfg = store.config
    started, release, finished = Event(), Event(), Event()
    outcomes = []

    def step():
        started.set()
        release.wait(3)
        try:
            with store.transaction(lease=store.lease) as db:
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('late_audit','unsafe')")
        except OutlookError as error:
            outcomes.append(error.code)
        finally:
            finished.set()

    worker = SourceWorker(SimpleNamespace(step=step))
    worker.tick()
    assert started.wait(1)
    worker.close()
    store.close()
    with StateStore(cfg, clock=clock) as restarted:
        release.set()
        assert finished.wait(1)
        assert outcomes == ["state_closed"]
        assert (
            restarted.db.execute("SELECT 1 FROM metadata WHERE key='late_audit'").fetchone() is None
        )


def test_database_transactions_are_serialized_between_collector_and_audit_threads(tmp_path):
    store, _, _, _, _, _ = setup(tmp_path)
    failures = []

    def write(prefix):
        try:
            for number in range(30):
                with store.transaction(lease=store.lease) as db:
                    db.execute(
                        "INSERT INTO metadata VALUES (?,?)", (f"thread-{prefix}-{number}", "safe")
                    )
        except Exception as error:
            failures.append(type(error).__name__)

    threads = [Thread(target=write, args=(prefix,)) for prefix in ("main", "audit")]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
        assert not failures and not any(t.is_alive() for t in threads)
        assert (
            store.db.execute("SELECT count(*) FROM metadata WHERE key LIKE 'thread-%'").fetchone()[
                0
            ]
            == 60
        )
        assert store.db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        store.close()
