import os
from pathlib import Path

import pytest

from agenttrace_foundation.database import Database, StorageUnavailable
from agenttrace_foundation.settings import Settings
from agenttrace_ingestion.dispatch import AnalysisQueue
from agenttrace_ingestion.notifications import NotificationValidator
from agenttrace_ingestion.pipeline import MailboxPipeline
from agenttrace_ingestion.store import IngestionStore
from tests.ingestion_support import GraphSource, cipher, enrollment, keypair, notification

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def workload(role):
    return Database(
        Settings(
            "127.0.0.1", 55432, ROOT / f"work/local/roles/{role}-password", "agenttrace_" + role
        )
    )


@pytest.fixture
def actual_roles():
    if os.environ.get("AGENTTRACE_INTEGRATION") != "1":
        pytest.skip("Explicit synthetic integration required")
    admin = Database(Settings.from_environment())
    enrolled = enrollment()
    hidden = enrollment()
    store = IngestionStore(admin, cipher())
    store.enroll(enrolled)
    store.enroll(hidden)
    with admin.connect() as connection:
        connection.execute(
            "DELETE FROM ingest_source_acl WHERE source_ref=%s", (hidden.source_ref,)
        )
    try:
        yield admin, enrolled, hidden
    finally:
        with admin.connect() as connection:
            for table in (
                "ingest_content_inputs",
                "ingest_dispatch",
                "ingest_versions",
                "ingest_copies",
                "ingest_events",
                "ingest_checkpoints",
                "ingest_subscriptions",
                "ingest_gaps",
                "ingest_audit_events",
                "ingest_transport_poison",
                "ingest_source_acl",
                "ingest_sources",
            ):
                connection.execute(
                    "DELETE FROM " + table + " WHERE source_ref=ANY(%s)",
                    ([enrolled.source_ref, hidden.source_ref],),
                )


def test_real_roles_preserve_source_and_axis_isolation(actual_roles):
    admin, config, hidden = actual_roles
    source = GraphSource(config)
    source.put()
    collector = IngestionStore(workload("collector"), cipher())
    pipeline = MailboxPipeline(collector, source.client(), keypair().public_key())
    assert pipeline.reconcile("pilot-folder") == 1
    assert pipeline.process_one()
    agent = AnalysisQueue(workload("attribution")).claim(config.source_ref, "agent")
    content = AnalysisQueue(workload("content")).claim(config.source_ref, "content")
    assert agent and content
    assert AnalysisQueue(workload("attribution")).claim(config.source_ref, "content") is None
    assert AnalysisQueue(workload("content")).claim(config.source_ref, "agent") is None
    assert AnalysisQueue(workload("content")).content_input(content)
    AnalysisQueue(workload("attribution")).complete(agent)
    AnalysisQueue(workload("content")).complete(content)
    api = IngestionStore(workload("api"), cipher())
    assert api.health(config.source_ref)["source_alias"] == "synthetic-pilot"
    from agenttrace_ingestion.contracts import IngestionError

    with pytest.raises(IngestionError, match="not_enrolled"):
        api.health(hidden.source_ref)
    event = NotificationValidator(hidden, cipher(), {"synthetic-subscription"}).parse(
        notification(hidden)
    )[0]
    with pytest.raises(StorageUnavailable):
        collector.accept([event])
    # Knowing a valid version reference must not allow a direct producer to attach
    # another source's work or content input to it; foreign keys enforce the pair.
    for table, statement, values in [
        (
            "ingest_dispatch",
            "INSERT INTO ingest_dispatch(version_ref,source_ref,axis) VALUES (%s,%s,'content')",
            (agent.version_ref, hidden.source_ref),
        ),
        (
            "ingest_content_inputs",
            "INSERT INTO ingest_content_inputs(version_ref,source_ref,capsule,expires_at) VALUES (%s,%s,%s,now()+interval '1 minute')",
            (agent.version_ref, hidden.source_ref, b"not-a-content-input"),
        ),
    ]:
        with pytest.raises(StorageUnavailable):
            with admin.connect() as connection:
                connection.execute(
                    "DELETE FROM " + table + " WHERE version_ref=%s", (agent.version_ref,)
                )
                connection.execute(statement, values)


@pytest.mark.parametrize(
    "role,statement",
    [
        ("api", "SELECT locator_cipher FROM ingest_events"),
        ("api", "SELECT cursor_cipher FROM ingest_checkpoints"),
        ("api", "SELECT capsule FROM ingest_content_inputs"),
        ("content", "SELECT locator_cipher FROM ingest_copies"),
        ("attribution", "SELECT capsule FROM ingest_content_inputs"),
        ("collector", "UPDATE ingest_source_acl SET db_role=db_role"),
        ("api", "UPDATE ingest_dispatch SET state='completed'"),
    ],
)
def test_actual_sql_logins_cannot_access_private_ingestion_fields_or_enrollment(
    actual_roles, role, statement
):
    with pytest.raises(StorageUnavailable):
        with workload(role).connect() as connection:
            connection.execute(statement)
