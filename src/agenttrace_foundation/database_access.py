"""Least-privilege local sandbox roles; bootstrap runs only as the migration owner."""

from __future__ import annotations

from pathlib import Path

from psycopg import Connection, sql
from psycopg.rows import DictRow

from .database import Database

WORKLOADS = ("api", "attribution", "content", "collector", "ledger")


def configure_local_roles(database: Database, secret_directory: Path) -> None:
    if database.schema != "public" or database.settings.database_user != "agenttrace":
        raise ValueError("local_migration_identity_required")
    with database.connect() as connection:
        # Provisioning statements must not put generated credentials into server logs.
        connection.execute("SET log_statement='none'")
        connection.execute("SET log_min_error_statement='panic'")
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        connection.execute("REVOKE ALL ON DATABASE agenttrace FROM PUBLIC")
        for workload in WORKLOADS:
            role = "agenttrace_" + workload
            password = (secret_directory / (workload + "-password")).read_text().strip()
            if len(password) < 32:
                raise ValueError("invalid_local_workload_credential")
            present = connection.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone()
            if not present:
                connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
            connection.execute(
                sql.SQL(
                    "ALTER ROLE {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
            connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE agenttrace TO {}").format(sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}").format(
                    sql.Identifier(role)
                )
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON foundation_schema TO {}").format(sql.Identifier(role))
            )
            connection.execute(
                sql.SQL("GRANT SELECT ON component_health TO {}").format(sql.Identifier(role))
            )
        for table in ("detection_jobs", "detection_decisions", "component_health"):
            connection.execute(
                sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(table))
            )
        for name, table, role, expression, command in [
            (
                "collector_jobs",
                "detection_jobs",
                "agenttrace_collector",
                "queue_name IN ('agent-evidence','content-analysis')",
                "ALL",
            ),
            (
                "attribution_jobs",
                "detection_jobs",
                "agenttrace_attribution",
                "queue_name='agent-evidence'",
                "ALL",
            ),
            (
                "content_jobs",
                "detection_jobs",
                "agenttrace_content",
                "queue_name='content-analysis'",
                "ALL",
            ),
            (
                "api_decisions",
                "detection_decisions",
                "agenttrace_api",
                "expires_at>now()",
                "SELECT",
            ),
            (
                "attribution_decisions",
                "detection_decisions",
                "agenttrace_attribution",
                "expires_at>now()",
                "ALL",
            ),
            ("api_health", "component_health", "agenttrace_api", "true", "SELECT"),
            (
                "attribution_health",
                "component_health",
                "agenttrace_attribution",
                "component='attribution'",
                "ALL",
            ),
            (
                "content_health",
                "component_health",
                "agenttrace_content",
                "component='content'",
                "ALL",
            ),
        ]:
            connection.execute(
                sql.SQL("DROP POLICY IF EXISTS {} ON {}").format(
                    sql.Identifier(name), sql.Identifier(table)
                )
            )
            connection.execute(
                sql.SQL("CREATE POLICY {} ON {} FOR {} TO {} USING ({})").format(
                    sql.Identifier(name),
                    sql.Identifier(table),
                    sql.SQL(command),
                    sql.Identifier(role),
                    sql.SQL(expression),
                )
            )
        connection.execute(
            "GRANT SELECT ON detection_jobs TO agenttrace_collector,agenttrace_attribution,agenttrace_content"
        )
        connection.execute(
            "GRANT INSERT(job_id,queue_name,idempotency_key,payload,visible_at) ON detection_jobs TO agenttrace_collector"
        )
        connection.execute(
            "GRANT UPDATE(idempotency_key) ON detection_jobs TO agenttrace_collector"
        )
        connection.execute(
            "GRANT UPDATE(visible_at,attempts,receipt,last_error_code,state) ON detection_jobs TO agenttrace_attribution,agenttrace_content"
        )
        connection.execute(
            "GRANT SELECT ON detection_decisions TO agenttrace_api,agenttrace_attribution"
        )
        connection.execute(
            "GRANT INSERT(decision_id,job_id,decision) ON detection_decisions TO agenttrace_attribution"
        )
        connection.execute(
            "GRANT INSERT,UPDATE ON component_health TO agenttrace_attribution,agenttrace_content"
        )
        _configure_ingestion_access(connection)
        configure_ledger_access(connection)


def configure_ledger_access(connection: Connection[DictRow]) -> None:
    """Apply in the current schema as migration owner; never accept runtime role names."""
    connection.execute("GRANT SELECT ON ledger_schema TO agenttrace_ledger")
    connection.execute("ALTER TABLE ledger_acl ENABLE ROW LEVEL SECURITY")
    connection.execute("DROP POLICY IF EXISTS ledger_own_acl ON ledger_acl")
    connection.execute(
        "CREATE POLICY ledger_own_acl ON ledger_acl FOR SELECT USING(db_role=current_user)"
    )
    connection.execute(
        "GRANT SELECT ON ledger_acl TO agenttrace_ledger,agenttrace_collector,agenttrace_api,agenttrace_attribution"
    )
    tables = (
        "ledger_scopes",
        "ledger_issuers",
        "ledger_keys",
        "ledger_observers",
        "ledger_revocations",
        "ledger_messages",
        "ledger_receipts",
        "ledger_conflicts",
        "ledger_inputs",
    )
    for table in tables:
        connection.execute(
            sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(table))
        )
        connection.execute(
            sql.SQL("DROP POLICY IF EXISTS ledger_scope_access ON {}").format(sql.Identifier(table))
        )
        expiry = (
            " AND expires_at>now()"
            if table in {"ledger_messages", "ledger_receipts", "ledger_conflicts", "ledger_inputs"}
            else ""
        )
        connection.execute(
            sql.SQL(
                "CREATE POLICY ledger_scope_access ON {} USING(EXISTS(SELECT 1 FROM ledger_acl a WHERE a.scope_ref={}.scope_ref AND a.db_role=current_user){})"
            ).format(sql.Identifier(table), sql.Identifier(table), sql.SQL(expiry))
        )
        connection.execute(
            sql.SQL(
                "REVOKE ALL ON {} FROM agenttrace_ledger,agenttrace_collector,agenttrace_api,agenttrace_attribution,agenttrace_content"
            ).format(sql.Identifier(table))
        )
        connection.execute(
            sql.SQL("GRANT SELECT ON {} TO agenttrace_ledger").format(sql.Identifier(table))
        )
    connection.execute("GRANT SELECT ON ledger_scopes TO agenttrace_collector")
    connection.execute("GRANT SELECT ON ledger_observers TO agenttrace_collector")
    connection.execute("GRANT SELECT,INSERT ON ledger_messages TO agenttrace_collector")
    connection.execute(
        "GRANT INSERT ON ledger_receipts,ledger_conflicts,ledger_inputs TO agenttrace_ledger"
    )
    connection.execute(
        "GRANT SELECT(scope_ref,message_ref,version_ref,source_ref,source_event_ref,source_schema_version,copy_role,message_state,observed_at,expires_at) ON ledger_messages TO agenttrace_api,agenttrace_attribution"
    )
    connection.execute(
        "GRANT SELECT(input_ref,scope_ref,message_ref,version_ref,schema_version,rule_version,history_epoch,revision,prior_input_ref,recorded_at,expires_at) ON ledger_inputs TO agenttrace_api,agenttrace_attribution"
    )


def _configure_ingestion_access(connection: Connection[DictRow]) -> None:
    # Keep operator enrollment separate from the runtime collector's data writes.
    cursor = connection
    cursor.execute("ALTER TABLE ingest_source_acl ENABLE ROW LEVEL SECURITY")
    cursor.execute("DROP POLICY IF EXISTS own_ingestion_acl ON ingest_source_acl")
    cursor.execute(
        "CREATE POLICY own_ingestion_acl ON ingest_source_acl FOR SELECT USING(db_role=current_user)"
    )
    cursor.execute(
        "GRANT SELECT ON ingest_source_acl TO agenttrace_collector,agenttrace_api,agenttrace_attribution,agenttrace_content"
    )
    tables = (
        "ingest_sources",
        "ingest_checkpoints",
        "ingest_subscriptions",
        "ingest_events",
        "ingest_copies",
        "ingest_versions",
        "ingest_dispatch",
        "ingest_content_inputs",
        "ingest_gaps",
        "ingest_audit_events",
        "ingest_transport_poison",
    )
    for table in tables:
        cursor.execute(
            sql.SQL("ALTER TABLE {} ENABLE ROW LEVEL SECURITY").format(sql.Identifier(table))
        )
        cursor.execute(
            sql.SQL("DROP POLICY IF EXISTS scoped_ingestion_access ON {}").format(
                sql.Identifier(table)
            )
        )
        cursor.execute(
            sql.SQL(
                "CREATE POLICY scoped_ingestion_access ON {} USING(EXISTS(SELECT 1 FROM ingest_source_acl acl WHERE acl.source_ref={}.source_ref AND acl.db_role=current_user))"
            ).format(sql.Identifier(table), sql.Identifier(table))
        )
    cursor.execute("GRANT SELECT ON ingest_sources TO agenttrace_collector")
    for table in tables[1:]:
        cursor.execute(
            sql.SQL("GRANT SELECT,INSERT,UPDATE ON {} TO agenttrace_collector").format(
                sql.Identifier(table)
            )
        )
    cursor.execute("GRANT DELETE ON ingest_content_inputs TO agenttrace_collector")
    cursor.execute(
        "GRANT SELECT(source_ref,event_ref,reason_code,received_at,expires_at) ON ingest_transport_poison TO agenttrace_api"
    )
    cursor.execute(
        "GRANT SELECT(source_ref,source_kind,source_alias,created_at) ON ingest_sources TO agenttrace_api,agenttrace_content,agenttrace_attribution"
    )
    cursor.execute(
        "GRANT SELECT(event_ref,source_ref,kind,event_time,received_at,expires_at,state,attempts,visible_at,last_error_code) ON ingest_events TO agenttrace_api"
    )
    cursor.execute(
        "GRANT SELECT(source_ref,partition_ref,coverage,reason_code,generation,last_success,next_attempt) ON ingest_checkpoints TO agenttrace_api"
    )
    cursor.execute(
        "GRANT SELECT(source_ref,state,expires_at) ON ingest_subscriptions TO agenttrace_api"
    )
    cursor.execute(
        "GRANT SELECT(source_ref,axis,state,version_ref) ON ingest_dispatch TO agenttrace_api"
    )
    cursor.execute(
        "GRANT SELECT(source_ref,reason_code,disposition,known_lost_events) ON ingest_gaps TO agenttrace_api"
    )
    cursor.execute("GRANT SELECT(source_ref,visibility) ON ingest_copies TO agenttrace_api")
    cursor.execute(
        "GRANT SELECT(message_ref,current_version,copy_role,delivery_ref) ON ingest_copies TO agenttrace_api"
    )
    cursor.execute(
        "GRANT SELECT(message_ref,source_ref,current_version) ON ingest_copies TO agenttrace_content,agenttrace_attribution"
    )
    cursor.execute("GRANT SELECT ON ingest_dispatch TO agenttrace_content,agenttrace_attribution")
    cursor.execute(
        "GRANT SELECT(source_ref,version_ref,message_ref,expires_at,obsolete,summary) ON ingest_versions TO agenttrace_content,agenttrace_attribution"
    )
    cursor.execute(
        "GRANT UPDATE(state,receipt,lease_until) ON ingest_dispatch TO agenttrace_content,agenttrace_attribution"
    )
    cursor.execute("DROP POLICY IF EXISTS scoped_ingestion_access ON ingest_dispatch")
    cursor.execute(
        "CREATE POLICY scoped_ingestion_access ON ingest_dispatch USING(EXISTS(SELECT 1 FROM ingest_source_acl acl WHERE acl.source_ref=ingest_dispatch.source_ref AND acl.db_role=current_user) AND (current_user IN ('agenttrace_api','agenttrace_collector') OR (current_user='agenttrace_content' AND axis='content') OR (current_user='agenttrace_attribution' AND axis='agent')))"
    )
    cursor.execute("GRANT SELECT ON ingest_content_inputs TO agenttrace_content")
    cursor.execute("DROP POLICY IF EXISTS scoped_ingestion_access ON ingest_content_inputs")
    cursor.execute(
        "CREATE POLICY scoped_ingestion_access ON ingest_content_inputs USING(EXISTS(SELECT 1 FROM ingest_source_acl acl WHERE acl.source_ref=ingest_content_inputs.source_ref AND acl.db_role=current_user) AND (current_user='agenttrace_collector' OR (current_user='agenttrace_content' AND expires_at>now() AND EXISTS(SELECT 1 FROM ingest_copies copy WHERE copy.current_version=ingest_content_inputs.version_ref))))"
    )
