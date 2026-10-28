from uuid import uuid4

import pytest

from agenttrace_ingestion.audit import ExchangeAuditCollector, OptionalActivityCollector
from agenttrace_ingestion.contracts import utc_now
from agenttrace_ingestion.graph_activity import GraphActivityCollector
from agenttrace_ingestion.store import IngestionStore
from tests.ingestion_support import CLIENT, TENANT, cipher, enrollment

pytestmark = pytest.mark.integration


class AuditSource:
    host = "graph.microsoft.com"

    def __init__(self, records):
        self.records = records
        self.requests = []
        self.pending = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if method == "POST":
            return {"id": "synthetic-query"}
        if url.endswith("synthetic-query"):
            return {"status": "running" if self.pending else "succeeded"}
        return {"value": self.records}


def test_exchange_audit_overlap_dedup_exact_filter_and_own_action_exclusion(database):
    config = enrollment()
    store = IngestionStore(database, cipher())
    store.enroll(config, kind="exchange_audit", alias="synthetic-audit")
    message = "<synthetic-message@example.invalid>"

    def record(id, operation, client, identifier):
        return {
            "id": id,
            "operation": operation,
            "createdDateTime": utc_now().isoformat(),
            "auditData": {
                "Operation": operation,
                "AppId": client,
                "Item": {"InternetMessageId": identifier},
                "Body": "RAW_AUDIT_CANARY_MUST_BE_DISCARDED",
            },
        }

    source = AuditSource(
        [
            record("send", "Send", "existing-agent", message),
            record("read", "MailItemsAccessed", str(CLIENT), message),
            record("outside", "Send", "existing-agent", "other@example.invalid"),
            record("substring", "Send", "existing-agent", "prefix" + message + "suffix"),
        ]
    )
    audit = ExchangeAuditCollector(
        store,
        source,
        config.source_ref,
        mailbox="synthetic@example.invalid",
        collector_clients={str(CLIENT)},
        allowed_message_ids={message},
    )
    assert audit.collect() == 0
    source.pending = True
    assert audit.collect() == 0
    with database.connect() as connection:
        assert connection.execute("SELECT count(*) AS n FROM ingest_gaps").fetchone()["n"] == 0
        connection.execute("UPDATE ingest_checkpoints SET next_attempt=now()")
    source.pending = False
    assert audit.collect() == 2
    assert audit.collect() == 0  # creates the overlapping next query
    assert audit.collect() == 0  # duplicate records are not reinserted
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM ingest_audit_events").fetchall()
    assert len(rows) == 2
    assert sum(r["signal_eligible"] for r in rows) == 1
    assert sum(r["collector_action"] for r in rows) == 1
    for row in rows:
        plaintext = store.cipher.open(
            bytes(row["evidence_cipher"]), context="audit:" + str(row["event_ref"])
        )
        assert "RAW_AUDIT_CANARY" not in repr(plaintext)
    second_query = (
        source.requests[-3][2]
        if source.requests[-3][0] == "POST"
        else next(v[2] for v in reversed(source.requests) if v[0] == "POST")
    )
    assert second_query["body"]["filterEndDateTime"]


def test_graph_activity_eligible_adapter_keeps_api_use_separate_from_ai_status(database):
    config = enrollment()
    store = IngestionStore(database, cipher())
    store.enroll(config, kind="graph_activity", alias="synthetic-activity")
    other = uuid4()

    class ActivitySource:
        host = "api.loganalytics.azure.com"

        def request(self, method, url, **kwargs):
            assert method == "POST" and "MicrosoftGraphActivityLogs" in kwargs["body"]["query"]
            return {
                "tables": [
                    {
                        "columns": [
                            {"name": name}
                            for name in [
                                "TimeGenerated",
                                "RequestId",
                                "AppId",
                                "RequestMethod",
                                "RequestUri",
                                "ResponseStatusCode",
                            ]
                        ],
                        "rows": [
                            [
                                utc_now().isoformat(),
                                "request-send",
                                str(other),
                                "POST",
                                "https://graph.microsoft.com/v1.0/me/sendMail",
                                202,
                            ],
                            [
                                utc_now().isoformat(),
                                "collector-read",
                                str(CLIENT),
                                "GET",
                                "https://graph.microsoft.com/v1.0/me/messages",
                                200,
                            ],
                        ],
                    }
                ]
            }

    collector = GraphActivityCollector(
        store,
        ActivitySource(),
        config.source_ref,
        uuid4(),
        tenant=TENANT,
        clients={CLIENT, other},
        collector_clients={CLIENT},
    )
    assert collector.collect() == 2
    assert collector.collect() == 0
    with database.connect() as connection:
        rows = connection.execute("SELECT * FROM ingest_audit_events").fetchall()
    assert len(rows) == 2 and sum(r["signal_eligible"] for r in rows) == 1
    assert store.health(config.source_ref)["agent_attribution"] == "not_established_by_ingestion"


@pytest.mark.parametrize("kind", ["office_activity", "graph_activity"])
def test_unconfigured_optional_sources_produce_explicit_gaps(database, kind):
    config = enrollment()
    store = IngestionStore(database, cipher())
    store.enroll(config, kind=kind, alias="optional-source")
    OptionalActivityCollector(store, config.source_ref, kind).unavailable()
    health = store.health(config.source_ref)
    assert health["checkpoints"][0]["coverage"] == "degraded"
    assert health["gaps"][0]["known_lost_events"] is None
