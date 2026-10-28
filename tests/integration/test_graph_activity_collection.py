from datetime import timedelta
from uuid import uuid4

import pytest

from agenttrace_ingestion.contracts import IngestionError, utc_now
from agenttrace_ingestion.graph_activity import GraphActivityCollector
from agenttrace_ingestion.store import IngestionStore
from tests.ingestion_support import CLIENT, MAILBOX, TENANT, cipher, enrollment

pytestmark = pytest.mark.integration
COLUMNS = [
    "TimeGenerated",
    "RequestId",
    "AppId",
    "RequestMethod",
    "RequestUri",
    "ResponseStatusCode",
]


class Source:
    host = "api.loganalytics.azure.com"

    def __init__(self, rows):
        self.rows = rows
        self.queries = []
        self.error = None

    def request(self, method, url, **kwargs):
        assert method == "POST"
        self.queries.append(kwargs["body"]["query"])
        if self.error:
            raise self.error
        return {"tables": [{"columns": [{"name": name} for name in COLUMNS], "rows": self.rows}]}


def setup(database, rows):
    config = enrollment()
    store = IngestionStore(database, cipher())
    store.enroll(config, kind="graph_activity", alias="graph-activity")
    other = uuid4()
    source = Source(rows)
    collector = GraphActivityCollector(
        store,
        source,
        config.source_ref,
        uuid4(),
        tenant=TENANT,
        clients={CLIENT, other},
        collector_clients={CLIENT},
        pilot_user=MAILBOX,
    )
    return store, source, collector, other


def ready(database):
    with database.connect() as connection:
        connection.execute("UPDATE ingest_checkpoints SET next_attempt=now()")


def test_delayed_arrivals_overlap_deduplicate_and_remove_uri_queries(database):
    store, source, collector, other = setup(database, [])
    timestamp = utc_now() - timedelta(minutes=50)
    source.rows = [
        [
            timestamp.isoformat(),
            "late-request",
            str(CLIENT),
            "GET",
            "https://graph.microsoft.com/v1.0/me/messages?search=PRIVATE_QUERY_CANARY",
            200,
        ]
    ]
    assert collector.collect() == 1
    ready(database)
    assert collector.collect() == 0
    assert timestamp.isoformat().split("T")[0] in source.queries[-1]
    with database.connect() as connection:
        event = connection.execute("SELECT * FROM ingest_audit_events").fetchone()
        checkpoint = connection.execute("SELECT * FROM ingest_checkpoints").fetchone()
    assert checkpoint["coverage"] == "current"
    assert event["collector_action"] and not event["signal_eligible"]
    plaintext = store.cipher.open(
        bytes(event["evidence_cipher"]), context="audit:" + str(event["event_ref"])
    )
    assert plaintext["RequestUri"].endswith("/me/messages") and "PRIVATE_QUERY_CANARY" not in repr(
        plaintext
    )


def test_empty_initial_delivery_is_pending_and_not_negative_agent_evidence(database):
    store, source, collector, other = setup(database, [])
    assert collector.collect() == 0
    health = store.health(collector.source_ref)
    assert health["checkpoints"][0]["coverage"] == "catching_up"
    assert health["checkpoints"][0]["reason_code"] == "graph_activity_delivery_pending"
    assert health["agent_attribution"] == "not_established_by_ingestion"


@pytest.mark.parametrize(
    "failure", ["partial", "overflow", "bad_row", "outside_client", "bad_uri", "throttled"]
)
def test_failed_windows_never_advance_checkpoints_or_partially_commit(database, failure):
    store, source, collector, other = setup(database, [])
    valid = [
        utc_now().isoformat(),
        "example-request",
        str(other),
        "POST",
        "https://graph.microsoft.com/v1.0/me/sendMail",
        202,
    ]
    source.rows = [valid]
    if failure == "partial":
        original = source.request

        def partial(*args, **kwargs):
            return {**original(*args, **kwargs), "error": {"code": "PartialError"}}

        source.request = partial
    elif failure == "overflow":
        source.rows = [valid] * 10001
    elif failure == "bad_row":
        source.rows = [valid, valid[:-1]]
    elif failure == "outside_client":
        source.rows = [valid, [*valid[:2], str(uuid4()), *valid[3:]]]
    elif failure == "bad_uri":
        source.rows = [valid, [*valid[:4], "https://example.invalid/secret", 202]]
    else:
        source.error = IngestionError("source_throttled", retryable=True, retry_after=60)
    with pytest.raises(IngestionError):
        collector.collect()
    with database.connect() as connection:
        assert (
            connection.execute("SELECT count(*) AS n FROM ingest_audit_events").fetchone()["n"] == 0
        )
        checkpoint = connection.execute("SELECT * FROM ingest_checkpoints").fetchone()
    assert checkpoint["watermark"] is None and checkpoint["coverage"] == "degraded"


def test_only_noncollector_successful_send_api_operations_are_correlation_candidates(database):
    store, source, collector, other = setup(database, [])
    source.rows = [
        [
            utc_now().isoformat(),
            "agent-send",
            str(other),
            "POST",
            "https://graph.microsoft.com/v1.0/me/messages/synthetic/send",
            202,
        ],
        [
            utc_now().isoformat(),
            "collector-query",
            str(CLIENT),
            "POST",
            "https://graph.microsoft.com/v1.0/security/auditLog/queries",
            201,
        ],
        [
            utc_now().isoformat(),
            "draft",
            str(other),
            "POST",
            "https://graph.microsoft.com/v1.0/me/messages",
            201,
        ],
        [
            utc_now().isoformat(),
            "denied-send",
            str(other),
            "POST",
            "https://graph.microsoft.com/v1.0/me/sendMail",
            403,
        ],
    ]
    assert collector.collect() == 4
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT operation,collector_action,signal_eligible FROM ingest_audit_events"
        ).fetchall()
    assert sum(r["signal_eligible"] for r in rows) == 1
    assert all(not r["signal_eligible"] for r in rows if r["collector_action"])
    assert store.health(collector.source_ref)["agent_attribution"] == "not_established_by_ingestion"
