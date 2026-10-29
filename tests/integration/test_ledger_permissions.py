from pathlib import Path
from uuid import uuid4

import pytest
from psycopg import sql

from agenttrace_foundation.database import Database, StorageUnavailable
from agenttrace_foundation.database_access import configure_ledger_access
from agenttrace_foundation.settings import Settings
from agenttrace_ledger.canonical import LedgerError
from agenttrace_ledger.store import EvidenceLedger
from tests.ingestion_support import CLIENT, TENANT, cipher
from tests.ledger_support import enrolled, observation, principal, send_fact, signed

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scoped_roles(database):
    with database.connect() as c:
        c.execute(
            sql.SQL(
                "GRANT USAGE ON SCHEMA {} TO agenttrace_ledger,agenttrace_collector,agenttrace_api,agenttrace_content,agenttrace_attribution"
            ).format(sql.Identifier(database.schema))
        )
        configure_ledger_access(c)

    def role(name):
        return Database(
            Settings(
                "127.0.0.1", 55432, ROOT / f"work/local/roles/{name}-password", "agenttrace_" + name
            ),
            schema=database.schema,
        )

    admin = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    issuer, key, private = enrolled(admin, message)
    admin.enroll_scope(
        message.tenant_id,
        message.mailbox_id,
        roles=(
            "agenttrace_ledger",
            "agenttrace_collector",
            "agenttrace_api",
            "agenttrace_attribution",
        ),
    )
    writer = EvidenceLedger(role("collector"), cipher(), {TENANT: bytes([9]) * 32})
    ref = writer.observe(message)
    hidden = observation(mailbox_id=uuid4())
    admin.enroll_scope(hidden.tenant_id, hidden.mailbox_id, roles=())
    admin.enroll_observer(hidden.tenant_id, hidden.mailbox_id, hidden.source_ref)
    hidden_ref = admin.observe(hidden)
    return admin, message, ref, issuer, key, private, role, hidden, hidden_ref


def test_effective_sql_logins_cannot_rewrite_enroll_read_raw_or_cross_mailbox(scoped_roles):
    admin, message, ref, issuer, key, private, role, hidden, hidden_ref = scoped_roles
    ledger = EvidenceLedger(role("ledger"), cipher(), {TENANT: bytes([9]) * 32})
    receipt = signed(message, ref, issuer, key, private, send_fact(message))
    ledger.submit(receipt, principal())
    ledger.record_inputs(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    with role("ledger").connect() as c:
        assert len(c.execute("SELECT * FROM ledger_messages").fetchall()) == 1
    with pytest.raises(LedgerError, match="not_found"):
        ledger.view(hidden.tenant_id, hidden.mailbox_id, hidden_ref, hidden.version_ref)
    for statement in [
        "UPDATE ledger_receipts SET record_digest=repeat('0',64)",
        "DELETE FROM ledger_receipts",
        "TRUNCATE ledger_receipts",
        "INSERT INTO ledger_keys SELECT * FROM ledger_keys",
        "INSERT INTO ledger_acl SELECT scope_ref,'agenttrace_content' FROM ledger_scopes",
        "UPDATE ledger_messages SET copy_role='sender'",
    ]:
        with pytest.raises(StorageUnavailable):
            with role("ledger").connect() as c:
                c.execute(statement)
    for name, table in [
        ("content", "ledger_messages"),
        ("api", "ledger_receipts"),
        ("attribution", "ledger_receipts"),
        ("collector", "ledger_receipts"),
    ]:
        with pytest.raises(StorageUnavailable):
            with role(name).connect() as c:
                c.execute("SELECT * FROM " + table)
    with role("api").connect() as c:
        assert len(c.execute("SELECT input_ref,revision FROM ledger_inputs").fetchall()) == 1
    with pytest.raises(StorageUnavailable):
        with role("api").connect() as c:
            c.execute("SELECT view_cipher FROM ledger_inputs")
    with pytest.raises(StorageUnavailable):
        ledger.enroll_key(
            message.tenant_id,
            message.mailbox_id,
            issuer,
            uuid4(),
            bytes(32),
            message.sent_at,
            message.observed_at,
        )


def test_append_triggers_and_scope_bindings_hold_even_for_owner_mistakes(scoped_roles):
    admin, message, ref, issuer, key, private, role, hidden, hidden_ref = scoped_roles
    admin.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())
    for statement in [
        "UPDATE ledger_receipts SET kind='generation'",
        "DELETE FROM ledger_receipts",
        "TRUNCATE ledger_receipts",
        "UPDATE ledger_keys SET public_key=decode(repeat('00',32),'hex')",
    ]:
        with pytest.raises(StorageUnavailable):
            with admin.database.connect() as c:
                c.execute(statement)
    with pytest.raises(StorageUnavailable):
        with role("ledger").connect() as c:
            c.execute(
                "INSERT INTO ledger_inputs(input_ref,scope_ref,message_ref,version_ref,schema_version,rule_version,revision,view_cipher,view_digest) VALUES(%s,%s,%s,%s,'1.0','correlation-v1',1,%s,%s)",
                (
                    uuid4(),
                    admin._scope(message.tenant_id, message.mailbox_id),
                    hidden_ref,
                    hidden.version_ref,
                    b"invalid",
                    "0" * 64,
                ),
            )
    with role("collector").connect() as c:
        assert (
            c.execute(
                "INSERT INTO ledger_messages SELECT * FROM ledger_messages WHERE scope_ref=%s",
                (admin._scope(hidden.tenant_id, hidden.mailbox_id),),
            ).rowcount
            == 0
        )


def test_loopback_http_with_real_runtime_identity_survives_server_restart(scoped_roles):
    import json
    import socket
    import threading
    import time
    from contextlib import contextmanager
    from dataclasses import replace
    from urllib.request import Request, urlopen

    import uvicorn

    from agenttrace_foundation.authorization import EntraTokenValidator
    from agenttrace_ledger.api import create_app
    from tests.development_identity import development_policy, development_token

    admin, message, ref, issuer, key, private, role, hidden, hidden_ref = scoped_roles
    policy = replace(
        development_policy(),
        subjects={str(CLIENT): frozenset({str(message.mailbox_id)})},
        messages={str(ref): str(message.mailbox_id)},
    )
    token = development_token(oid=str(CLIENT))

    @contextmanager
    def serving():
        ledger = EvidenceLedger(role("ledger"), cipher(), {TENANT: bytes([9]) * 32})
        app = create_app(ledger, policy=policy, validator=EntraTokenValidator(policy))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert server.started
                yield "http://127.0.0.1:" + str(sock.getsockname()[1])
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                assert not thread.is_alive()

    def request(base, path, body=None, access=token):
        req = Request(
            base + path,
            data=body,
            headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"},
        )
        with urlopen(req, timeout=10) as response:
            return json.load(response)

    path = f"/v1/evidence/messages/{ref}/versions/{message.version_ref}"
    envelope = signed(message, ref, issuer, key, private, send_fact(message))
    investigator = development_token(
        oid=str(CLIENT), idtyp="user", scp="Detection.Read", roles=["Detection.Investigator"]
    )
    with serving() as base:
        assert "evidence_ref" in request(
            base, "/v1/evidence/receipts", envelope.model_dump_json().encode()
        )
        initial = request(base, path)
        assert initial["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
        input_ref = request(base, path + "/inputs", b"", investigator)["input_ref"]
    with serving() as base:
        assert request(base, path) == initial
        history = request(base, f"/v1/evidence/messages/{ref}/history")
        assert history["history"][0]["input_ref"] == input_ref
