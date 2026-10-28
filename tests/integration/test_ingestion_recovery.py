from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from uuid import uuid4

import pytest

from agenttrace_ingestion.contracts import IngestionError, utc_now
from agenttrace_ingestion.notifications import NotificationValidator
from agenttrace_ingestion.pipeline import MailboxPipeline
from agenttrace_ingestion.queue_transport import AzureNotificationQueue
from agenttrace_ingestion.store import IngestionStore
from tests.ingestion_support import GraphSource, cipher, enrollment, keypair, notification

pytestmark = pytest.mark.integration


def setup(database):
    config = enrollment()
    store = IngestionStore(database, cipher())
    store.enroll(config)
    source = GraphSource(config)
    pipeline = MailboxPipeline(store, source.client(), keypair().public_key())
    return config, store, source, pipeline


def test_parallel_claims_have_one_winner_and_checkpoint_receipt_is_fenced(database):
    config, store, source, pipeline = setup(database)
    validator = NotificationValidator(config, cipher(), {"synthetic-subscription"})
    store.accept(validator.parse(notification(config)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: store.claim(config.source_ref), range(2)))
    assert sum(c is not None for c in claims) == 1
    partition = uuid4()
    first = store.claim_checkpoint(config.source_ref, partition)
    assert first and store.claim_checkpoint(config.source_ref, partition) is None
    with database.connect() as connection:
        connection.execute("UPDATE ingest_checkpoints SET lease_until=now()-interval '1 second'")
    second = store.claim_checkpoint(config.source_ref, partition)
    assert second and second.receipt != first.receipt
    with pytest.raises(IngestionError, match="checkpoint_lease_lost"):
        store.commit_page(first, [], source.delta_url(), final=True)
    store.commit_page(second, [], source.delta_url(), final=True)


def test_renewal_and_expired_subscription_recreation_are_bounded(database):
    config, store, source, pipeline = setup(database)
    # The fixture returns a new ID for a replacement, as the actual service does.
    original = source.open
    from tests.ingestion_support import Response

    def open_request(request, timeout):
        if request.method == "POST" and request.full_url.endswith("/subscriptions"):
            source.calls.append((request.method, request.full_url, {}, request.data))
            return Response(
                {
                    "id": "replacement-" + str(len(source.calls)),
                    "expirationDateTime": (utc_now() + timedelta(days=2)).isoformat(),
                }
            )
        return original(request, timeout)

    pipeline.mailbox.transport._open = open_request
    store.save_subscription(
        config.source_ref, "existing", utc_now() + timedelta(hours=1), folder_id="pilot-folder"
    )
    assert pipeline.renew() == 1
    assert pipeline.renew() == 0
    with database.connect() as connection:
        connection.execute("UPDATE ingest_subscriptions SET expires_at=now()-interval '1 second'")
    # Both configured folders need an active subscription after an expired one.
    assert pipeline.renew("https://example.invalid/notifications") == 2
    assert pipeline.renew("https://example.invalid/notifications") == 0
    assert any(
        g["reason_code"] == "subscription_expired_or_removed"
        for g in store.health(config.source_ref)["gaps"]
    )


def test_invalid_native_payload_is_quarantined_before_receipt_deletion(database):
    config, store, source, pipeline = setup(database)
    actions = []

    def open_request(request, timeout):
        actions.append(request.method)
        return BytesIO(
            b"<QueueMessagesList><QueueMessage><MessageId>native</MessageId><PopReceipt>receipt</PopReceipt><DequeueCount>5</DequeueCount><MessageText>malformed-raw-canary</MessageText></QueueMessage></QueueMessagesList>"
            if request.method == "GET"
            else b""
        )

    validator = NotificationValidator(config, cipher(), {"synthetic-subscription"})
    queue = AzureNotificationQueue("syntheticstorage", lambda **_: "synthetic", opener=open_request)
    assert queue.receive_one(store, validator)
    with database.connect() as connection:
        poison = connection.execute("SELECT * FROM ingest_transport_poison").fetchall()
    assert len(poison) == 1 and "malformed-raw-canary" not in repr(poison)
    assert actions == ["GET", "DELETE"]
    health = store.health(config.source_ref)
    assert health["native_poison_count"] == 1
    assert health["gaps"][0]["disposition"] == "unrecoverable"
