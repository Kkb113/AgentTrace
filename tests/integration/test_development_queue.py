from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from agenttrace_attribution import assess_authored_example
from agenttrace_contracts import DetectionJob, utc_now
from fastapi.testclient import TestClient

from agenttrace_foundation.api import create_app
from agenttrace_foundation.queue import DevelopmentQueue, Lease
from agenttrace_foundation.service import process_one
from agenttrace_foundation.store import DecisionStore

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def job(ref="synthetic-reference"):
    return DetectionJob(fixture_ref="authored_contract_example", message_ref=ref)


def test_idempotency_replay_and_conflict(database):
    queue = DevelopmentQueue(database, "agent-evidence")
    original = queue.enqueue(job(), "key")
    assert queue.enqueue(job(), "key") == original
    with pytest.raises(ValueError, match="conflicting_idempotency"):
        queue.enqueue(job("different"), "key")


def test_visibility_expiry_redelivery_and_stale_receipts(database):
    queue = DevelopmentQueue(database, "agent-evidence")
    queue.enqueue(job(), "key")
    now = utc_now() + timedelta(seconds=1)
    first = queue.receive(now=now, visibility_seconds=1)
    assert first is not None
    assert queue.receive(now=now) is None
    second = queue.receive(now=now + timedelta(seconds=2), visibility_seconds=30)
    assert second is not None and second.job_id == first.job_id and second.receipt != first.receipt
    assert not queue.acknowledge(first, now=now + timedelta(seconds=2))
    assert queue.acknowledge(second, now=now + timedelta(seconds=2))
    assert queue.receive(now=now + timedelta(seconds=40)) is None


def test_retry_and_poison_are_explicit(database):
    queue = DevelopmentQueue(database, "agent-evidence", maximum_attempts=2)
    job_id = queue.enqueue(job(), "key")
    lease = queue.receive()
    assert lease is not None and queue.retry(lease, delay_seconds=0)
    lease = queue.receive()
    assert lease is not None and lease.attempts == 2
    assert queue.retry(lease, delay_seconds=0)
    assert queue.receive() is None
    with database.connect() as connection:
        state = connection.execute(
            "SELECT state,last_error_code FROM detection_jobs WHERE job_id=%s", (job_id,)
        ).fetchone()
    assert state == {"state": "poison", "last_error_code": "maximum_attempts_exceeded"}


def test_queues_are_separate_and_receipt_is_queue_scoped(database):
    primary = DevelopmentQueue(database, "agent-evidence")
    content = DevelopmentQueue(database, "content-analysis")
    primary.enqueue(job(), "key")
    assert content.receive() is None
    lease = primary.receive()
    assert lease is not None
    assert not content.acknowledge(lease)
    assert not primary.acknowledge(Lease(lease.job_id, uuid4(), lease.payload, lease.attempts))


def test_concurrent_receivers_do_not_share_a_live_lease(database):
    queue = DevelopmentQueue(database, "agent-evidence")
    for index in range(8):
        queue.enqueue(job(), f"key-{index}")
    with ThreadPoolExecutor(max_workers=8) as workers:
        leases = list(workers.map(lambda _: queue.receive(), range(8)))
    assert all(lease is not None for lease in leases)
    assert len({lease.job_id for lease in leases if lease is not None}) == 8


def test_queue_worker_store_read_only_api_round_trip(database):
    queue = DevelopmentQueue(database, "agent-evidence")
    queue.enqueue(job("synthetic-example"), "round-trip")
    decision = process_one(database, ROOT)
    assert decision is not None
    assert process_one(database, ROOT) is None
    store = DecisionStore(database)
    store.heartbeat("attribution")
    store.heartbeat("content")
    from tests.development_identity import development_policy, development_token

    client = TestClient(create_app(database, policy=development_policy()))
    client.headers.update({"Authorization": "Bearer " + development_token()})
    assert client.get("/health/ready").status_code == 200
    response = client.get(f"/v1/decisions/{decision.decision_id}")
    assert response.status_code == 200
    findings = response.json()["findings"]
    assert findings["agent_send_attribution"]["flagged"] is True
    assert findings["content_assessment"]["flagged"] is None
    assert client.post("/sendMail", json={}).status_code == 404
    assert client.post("/v1/decisions", json={}).status_code == 404
    assert client.get(f"/v1/decisions/{uuid4()}").status_code == 404


def test_result_and_acknowledgement_require_the_current_lease(database):
    queue = DevelopmentQueue(database, "agent-evidence")
    queue.enqueue(job(), "atomic-completion")
    lease = queue.receive()
    assert lease is not None
    findings = assess_authored_example(ROOT / "examples/evidence-contract")
    store = DecisionStore(database)
    forged = Lease(lease.job_id, uuid4(), lease.payload, lease.attempts)
    assert store.complete("agent-evidence", forged, findings) is None
    with database.connect() as connection:
        row = connection.execute("SELECT count(*) AS total FROM detection_decisions").fetchone()
    assert row["total"] == 0
    with pytest.raises(ValueError, match="cannot_complete_agent"):
        store.complete("content-analysis", lease, findings)
    decision = store.complete("agent-evidence", lease, findings)
    assert decision is not None
    assert store.complete("agent-evidence", lease, findings) is None
    with database.connect() as connection:
        connection.execute(
            "UPDATE detection_decisions SET expires_at=%s WHERE decision_id=%s",
            (utc_now() - timedelta(days=1), decision.decision_id),
        )
    assert store.get(decision.decision_id) is None
