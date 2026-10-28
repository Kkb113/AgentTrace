import json
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agenttrace_foundation.database import StorageUnavailable
from agenttrace_ingestion.api import create_app
from agenttrace_ingestion.contracts import IngestionError, utc_now
from agenttrace_ingestion.dispatch import AnalysisQueue
from agenttrace_ingestion.notifications import NotificationValidator
from agenttrace_ingestion.pipeline import MailboxPipeline
from agenttrace_ingestion.protection import open_content
from agenttrace_ingestion.store import IngestionStore
from tests.ingestion_support import BODY, GraphSource, cipher, enrollment, keypair, notification

pytestmark = pytest.mark.integration


@pytest.fixture
def sandbox(database):
    config = enrollment()
    store = IngestionStore(database, cipher())
    store.enroll(config)
    source = GraphSource(config)
    key = keypair()
    pipeline = MailboxPipeline(store, source.client(), key.public_key())
    validator = NotificationValidator(config, cipher(), {"synthetic-subscription"})
    return config, store, source, key, pipeline, validator


def rows(database, table):
    assert table.startswith("ingest_")
    with database.connect() as connection:
        return connection.execute("SELECT * FROM " + table).fetchall()


def test_end_to_end_webhook_commit_reconcile_extract_and_independent_analysis(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    source.put(body=BODY + "\n> Inherited canary excluded from authored text")
    with TestClient(create_app(store, validator)) as client:
        challenge = client.post("/v1/notifications?validationToken=synthetic%20challenge")
        assert challenge.status_code == 200 and challenge.text == "synthetic challenge"
        response = client.post("/v1/notifications", content=notification(config))
        assert response.status_code == 202
        assert rows(database, "ingest_events")[0]["state"] == "pending"
        assert client.get(f"/v1/ingestion/sources/{config.source_ref}").status_code == 401
    assert pipeline.process_one()
    copies = rows(database, "ingest_copies")
    assert len(copies) == 1 and copies[0]["copy_role"] == "unknown"
    versions = rows(database, "ingest_versions")
    assert versions[0]["summary"]["region_counts"]["quoted"] == 1
    assert versions[0]["summary"]["statistically_eligible"]
    dispatch = AnalysisQueue(database)
    agent = dispatch.claim(config.source_ref, "agent")
    content = dispatch.claim(config.source_ref, "content")
    assert agent and content and agent.version_ref == content.version_ref
    dispatch.complete(agent)
    assert any(
        w["axis"] == "content" and w["state"] == "leased" for w in rows(database, "ingest_dispatch")
    )
    capsule = dispatch.content_input(content)
    assert capsule is not None and BODY.encode() not in capsule
    # PostgreSQL rounds timestamp storage to microseconds; serializer preserves it.
    actual = json.loads(capsule)["expires_at"]
    from datetime import datetime

    decoded = open_content(
        capsule,
        key,
        version_ref=content.version_ref,
        expires_at=datetime.fromisoformat(actual),
        now=utc_now(),
    )
    assert "Inherited canary" not in decoded["authored_text"]
    assert decoded["authored_text"] == BODY.strip()
    dispatch.complete(content)
    health = store.health(config.source_ref)
    assert health["agent_attribution"] == "not_established_by_ingestion"
    assert health["content_scorer"] == "not_installed"
    assert not rows(database, "ingest_audit_events")


def test_database_failure_before_commit_returns_503_and_no_ack(sandbox, monkeypatch):
    config, store, source, key, pipeline, validator = sandbox

    def unavailable(*_):
        raise StorageUnavailable("synthetic_failure")

    monkeypatch.setattr(store, "accept", unavailable)
    with TestClient(create_app(store, validator)) as client:
        assert client.post("/v1/notifications", content=notification(config)).status_code == 503


def test_atomic_batch_rolls_back_all_items_on_foreign_source(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    valid = validator.parse(notification(config))[0]
    invalid = valid.model_copy(update={"source_ref": uuid4(), "event_ref": uuid4()})
    with pytest.raises(StorageUnavailable):
        store.accept([valid, invalid])
    assert not rows(database, "ingest_events")


def test_duplicate_out_of_order_move_and_edit_supersede_stale_work(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    old_time = utc_now() - timedelta(minutes=2)
    source.put(modified=old_time)
    event = validator.parse(notification(config))[0]
    assert store.accept([event, event]) == 1
    assert pipeline.process_one()
    queue = AnalysisQueue(database)
    old = queue.claim(config.source_ref, "content")
    assert old
    old_snapshot = source.client().read("MessageCaseSensitive")
    source.put(version="edited-version", body="Revised content", folder="pilot-child")
    pipeline.reconcile("pilot-child")
    assert pipeline.process_one()
    with pytest.raises(IngestionError, match="version_or_lease_lost"):
        queue.complete(old)
    assert queue.content_input(old) is None
    assert len(rows(database, "ingest_copies")) == 1
    assert len(rows(database, "ingest_versions")) == 2
    assert sum(v["obsolete"] for v in rows(database, "ingest_versions")) == 1
    # Delayed older response cannot overwrite the newer current version.
    delayed = event.model_copy(update={"event_ref": uuid4()})
    store.accept([delayed])
    lease = store.claim(config.source_ref)
    assert lease
    store.complete_message(
        lease, old_snapshot, pipeline.extractor.extract(BODY, "text"), key.public_key()
    )
    current = rows(database, "ingest_copies")[0]["current_version"]
    assert current != old.version_ref
    pipeline.reconcile("pilot-folder")
    pipeline.reconcile("pilot-child")
    while pipeline.process_one():
        pass
    assert len(rows(database, "ingest_copies")) == 1 and len(rows(database, "ingest_versions")) == 2


def test_checkpoint_and_page_are_one_transaction_restart_recovers(sandbox, database, monkeypatch):
    config, store, source, key, pipeline, validator = sandbox
    source.put()
    original = store._persist

    def fail_after_insert(connection, event):
        original(connection, event)
        raise IngestionError("controlled_crash_before_commit", retryable=True)

    monkeypatch.setattr(store, "_persist", fail_after_insert)
    with pytest.raises(IngestionError):
        pipeline.reconcile("pilot-folder")
    assert not rows(database, "ingest_events")
    assert rows(database, "ingest_checkpoints")[0]["cursor_cipher"] is None
    monkeypatch.setattr(store, "_persist", original)
    with database.connect() as connection:
        connection.execute("UPDATE ingest_checkpoints SET next_attempt=now()")
    assert pipeline.reconcile("pilot-folder") == 1
    assert pipeline.process_one()
    assert pipeline.reconcile("pilot-folder") == 0
    assert len(rows(database, "ingest_events")) == 1


def test_expired_delta_full_resync_recovers_state_and_preserves_historical_gap(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    source.put()
    assert pipeline.reconcile("pilot-folder") == 1
    assert pipeline.process_one()
    source.error = 410
    with pytest.raises(IngestionError, match="cursor_expired"):
        pipeline.reconcile("pilot-folder")
    gap = rows(database, "ingest_gaps")[0]
    assert gap["disposition"] == "open" and gap["known_lost_events"] is None
    # One message existed and disappeared entirely during the outage. Neither
    # notification nor delta can reconstruct its unobserved historical versions.
    with database.connect() as connection:
        connection.execute("UPDATE ingest_gaps SET known_lost_events=1")
        connection.execute("UPDATE ingest_checkpoints SET next_attempt=now()")
    source.put("recovered-after-outage")
    assert pipeline.reconcile("pilot-folder") == 2
    while pipeline.process_one():
        pass
    gap = rows(database, "ingest_gaps")[0]
    assert gap["disposition"] == "recovered_current_state" and gap["known_lost_events"] == 1
    assert len(rows(database, "ingest_copies")) == 2
    assert len(rows(database, "ingest_versions")) == 2


def test_lost_receipts_retry_poison_replay_and_retention(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    source.put()
    store.accept(validator.parse(notification(config)))
    first = store.claim(config.source_ref)
    assert first
    with database.connect() as connection:
        connection.execute("UPDATE ingest_events SET visible_at=now()-interval '1 second'")
    second = store.claim(config.source_ref)
    assert second and second.receipt != first.receipt
    with pytest.raises(IngestionError, match="lease_lost"):
        store.retry(first, IngestionError("source_temporarily_unavailable", retryable=True))
    store.retry(second, IngestionError("source_access_denied"))
    assert rows(database, "ingest_events")[0]["state"] == "poison"
    assert store.replay(config.source_ref, second.event_ref)
    assert pipeline.process_one()
    assert rows(database, "ingest_events")[0]["state"] == "processed"
    with database.connect() as connection:
        connection.execute("UPDATE ingest_content_inputs SET expires_at=now()-interval '1 second'")
        connection.execute("UPDATE ingest_versions SET expires_at=now()-interval '1 second'")
        connection.execute("UPDATE ingest_events SET expires_at=now()-interval '1 second'")
    counts = store.purge()
    assert counts["ingest_versions"] == 1 and counts["ingest_events"] == 1
    assert not rows(database, "ingest_dispatch") and not rows(database, "ingest_content_inputs")


@pytest.mark.parametrize("change", ["missed", "subscriptionRemoved", "reauthorizationRequired"])
def test_lifecycle_changes_coverage_not_actor_verdict(sandbox, database, change):
    config, store, source, key, pipeline, validator = sandbox
    store.save_subscription(
        config.source_ref, "synthetic-subscription", utc_now() + timedelta(days=1)
    )
    pipeline.reconcile("pilot-folder")
    store.accept(validator.parse(notification(config, change=change)))
    assert pipeline.process_one()
    assert rows(database, "ingest_checkpoints")[0]["coverage"] == "degraded"
    assert rows(database, "ingest_gaps")[0]["reason_code"] == "subscription_lifecycle_gap"
    assert not rows(database, "ingest_versions")


def test_inaccessible_deleted_moved_messages_are_visible_unknown_gaps(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    source.put()
    pipeline.reconcile("pilot-folder")
    pipeline.process_one()
    source.put(folder="out-of-scope")
    store.accept(
        validator.parse(notification(config, event="moved", cloud=True), cloud_events=True)
    )
    pipeline.process_one()
    assert rows(database, "ingest_copies")[0]["visibility"] == "moved_out_of_scope"
    source.messages.clear()
    store.accept(validator.parse(notification(config, event="gone", cloud=True), cloud_events=True))
    pipeline.process_one()
    assert rows(database, "ingest_copies")[0]["visibility"] == "deleted_or_unavailable"
    assert len(rows(database, "ingest_gaps")) == 2


def test_ciphertext_corruption_is_durably_poisoned_without_infinite_retry(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    store.accept(validator.parse(notification(config)))
    with database.connect() as connection:
        connection.execute("UPDATE ingest_events SET locator_cipher=%s", (b"corrupted",))
    with pytest.raises(IngestionError, match="invalid_encrypted_event"):
        store.claim(config.source_ref)
    assert rows(database, "ingest_events")[0]["state"] == "poison"
    assert store.claim(config.source_ref) is None


def test_canary_never_enters_queue_locator_summary_or_health(sandbox, database, capsys):
    config, store, source, key, pipeline, validator = sandbox
    canary = "RAW_BODY_CANARY_NEVER_IN_QUEUE_DIAGNOSTICS"
    source.put(body=BODY + canary)
    pipeline.reconcile("pilot-folder")
    pipeline.process_one()
    for table in [
        "ingest_events",
        "ingest_checkpoints",
        "ingest_copies",
        "ingest_versions",
        "ingest_dispatch",
        "ingest_content_inputs",
    ]:
        assert canary not in repr(rows(database, table))
    assert canary not in json.dumps(store.health(config.source_ref))
    assert canary not in capsys.readouterr().out


def test_sender_recipient_copies_do_not_share_executor_or_versions(sandbox, database):
    config, store, source, key, pipeline, validator = sandbox
    source.put("SentCopy")
    source.put("ReceivedCopy")
    pipeline.reconcile("pilot-folder")
    while pipeline.process_one():
        pass
    copies = rows(database, "ingest_copies")
    assert len(copies) == 2 and len({c["message_ref"] for c in copies}) == 2
    assert all(c["copy_role"] == "unknown" for c in copies)
    assert len({c["delivery_ref"] for c in copies}) == 1
