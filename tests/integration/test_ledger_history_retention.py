from uuid import uuid4

import pytest

from agenttrace_foundation.database import StorageUnavailable
from agenttrace_ledger.store import EvidenceLedger
from tests.ingestion_support import TENANT, cipher
from tests.ledger_support import enrolled, observation

pytestmark = pytest.mark.integration


def test_nonempty_pre_epoch_preview_requires_review_and_preserves_records(database):
    from fastapi.testclient import TestClient

    from agenttrace_foundation.authorization import EntraTokenValidator
    from agenttrace_ledger.api import create_app
    from tests.development_identity import development_policy

    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    enrolled(ledger, message)
    ref = ledger.observe(message)
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    policy = development_policy()
    client = TestClient(create_app(ledger, policy=policy, validator=EntraTokenValidator(policy)))
    assert client.get("/health/ready").status_code == 200
    # Simulate only this disposable schema's older development layout.
    with database.connect() as connection:
        connection.execute("ALTER TABLE ledger_inputs DROP COLUMN history_epoch CASCADE")
    assert client.get("/health/ready").status_code == 503
    with pytest.raises(StorageUnavailable):
        database.migrate()
    with database.connect() as connection:
        assert (
            connection.execute("SELECT count(*) AS count FROM ledger_inputs").fetchone()["count"]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) AS count FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='ledger_inputs' AND column_name='history_epoch'"
            ).fetchone()["count"]
            == 0
        )


def test_expired_unpurged_history_cannot_block_a_new_reassessment_epoch(database):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    enrolled(ledger, message)
    ref = ledger.observe(message)
    old_epoch = uuid4()
    with database.connect() as connection:
        connection.execute(
            """INSERT INTO ledger_inputs(input_ref,scope_ref,message_ref,version_ref,
               schema_version,rule_version,revision,history_epoch,view_cipher,view_digest,recorded_at,expires_at)
               VALUES(%s,%s,%s,%s,'1.0','correlation-v1',1,%s,%s,%s,
               now()-interval '31 days',now()-interval '1 day')""",
            (
                uuid4(),
                ledger._scope(message.tenant_id, message.mailbox_id),
                ref,
                message.version_ref,
                old_epoch,
                b"expired-metadata",
                "0" * 64,
            ),
        )
    assert ledger.history(message.tenant_id, message.mailbox_id, ref) == []
    first = ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    second = ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    history = ledger.history(message.tenant_id, message.mailbox_id, ref)
    assert [row["revision"] for row in history] == [1, 2]
    assert history[0]["history_epoch"] == str(first) != str(old_epoch)
    assert history[1]["history_epoch"] == history[0]["history_epoch"]
    assert history[1]["input_ref"] == str(second)
    assert history[1]["prior_input_ref"] == str(first)
    with database.connect() as connection:
        assert (
            connection.execute("SELECT count(*) AS count FROM ledger_inputs").fetchone()["count"]
            == 3
        )
