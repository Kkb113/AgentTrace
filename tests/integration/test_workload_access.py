import os
import time
from pathlib import Path
from uuid import uuid4

import pytest
from agenttrace_contracts import DetectionJob, utc_now
from psycopg.types.json import Jsonb

from agenttrace_foundation.database import Database, StorageUnavailable
from agenttrace_foundation.queue import DevelopmentQueue
from agenttrace_foundation.service import process_one
from agenttrace_foundation.settings import Settings
from agenttrace_foundation.store import DecisionStore

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def workload(role):
    if os.environ.get("AGENTTRACE_INTEGRATION") != "1":
        pytest.skip("Explicit sandbox integration required")
    return Database(
        Settings(
            "127.0.0.1", 55432, ROOT / f"work/local/roles/{role}-password", "agenttrace_" + role
        )
    )


@pytest.mark.parametrize(
    "role,statement",
    [
        ("api", "SELECT * FROM detection_jobs LIMIT 1"),
        ("api", "UPDATE detection_decisions SET expires_at=now() WHERE false"),
        ("content", "SELECT * FROM detection_decisions LIMIT 1"),
        ("collector", "SELECT * FROM detection_decisions LIMIT 1"),
        ("content", "SELECT * FROM pg_authid LIMIT 1"),
        ("attribution", "SELECT * FROM pg_authid LIMIT 1"),
    ],
)
def test_actual_sql_logins_cannot_cross_their_privilege_boundary(role, statement):
    database = workload(role)
    assert database.healthy()
    with pytest.raises(StorageUnavailable):
        with database.connect() as connection:
            connection.execute(statement)


def test_database_queue_row_security_and_expired_decision_access():
    collector, attribution, content, api = [
        workload(role) for role in ["collector", "attribution", "content", "api"]
    ]
    jobs = []
    admin = Database(Settings.from_environment())
    try:
        agent_id = DevelopmentQueue(collector, "agent-evidence").enqueue(
            DetectionJob(fixture_ref="authored_contract_example", message_ref="synthetic-example"),
            uuid4().hex,
        )
        content_id = DevelopmentQueue(collector, "content-analysis").enqueue(
            DetectionJob(fixture_ref="authored_contract_example", message_ref="synthetic-example"),
            uuid4().hex,
        )
        jobs.extend([agent_id, content_id])
        for database, excluded in [(attribution, content_id), (content, agent_id)]:
            with database.connect() as connection:
                assert (
                    connection.execute(
                        "SELECT job_id FROM detection_jobs WHERE job_id=%s", (excluded,)
                    ).fetchone()
                    is None
                )
                assert (
                    connection.execute(
                        "UPDATE detection_jobs SET attempts=attempts+1 WHERE job_id=%s", (excluded,)
                    ).rowcount
                    == 0
                )
        process_one(attribution, ROOT)
        # Other independent smoke jobs may precede this test's row.
        row = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with admin.connect() as connection:
                row = connection.execute(
                    "SELECT decision_id FROM detection_decisions WHERE job_id=%s", (agent_id,)
                ).fetchone()
            if row:
                break
            process_one(attribution, ROOT)
            time.sleep(0.05)
        assert row is not None
        assert DecisionStore(api).get(row["decision_id"]) is not None
        with admin.connect() as connection:
            connection.execute(
                "UPDATE detection_decisions SET expires_at=now()-interval '1 second' WHERE decision_id=%s",
                (row["decision_id"],),
            )
        with api.connect() as connection:
            assert (
                connection.execute(
                    "SELECT decision FROM detection_decisions WHERE decision_id=%s",
                    (row["decision_id"],),
                ).fetchone()
                is None
            )
        assert DecisionStore(api).get(row["decision_id"]) is None
    finally:
        with admin.connect() as connection:
            connection.execute("DELETE FROM detection_decisions WHERE job_id=ANY(%s)", (jobs,))
            connection.execute("DELETE FROM detection_jobs WHERE job_id=ANY(%s)", (jobs,))


def test_direct_producer_sql_cannot_put_body_text_in_reference_queue():
    collector = workload("collector")
    with pytest.raises(StorageUnavailable):
        with collector.connect() as connection:
            connection.execute(
                "INSERT INTO detection_jobs(job_id,queue_name,idempotency_key,payload,visible_at) VALUES (%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    "agent-evidence",
                    uuid4().hex,
                    Jsonb(
                        {
                            "schema_version": "1.0",
                            "fixture_ref": "authored_contract_example",
                            "message_ref": "synthetic-example",
                            "body": "Synthetic body must not enter a queue",
                        }
                    ),
                    utc_now(),
                ),
            )


def test_running_database_does_not_log_statements_parameters_or_error_row_details():
    workload("api")  # Enforces explicit integration opt-in.
    database = Database(Settings.from_environment())
    with database.connect() as connection:
        for setting, expected in {
            "log_statement": "none",
            "log_min_error_statement": "panic",
            "log_error_verbosity": "terse",
            "log_parameter_max_length": "0",
            "log_parameter_max_length_on_error": "0",
        }.items():
            assert connection.execute("SHOW " + setting).fetchone()[setting] == expected
