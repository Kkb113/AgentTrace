"""Least-privilege local sandbox roles; bootstrap runs only as the migration owner."""

from __future__ import annotations

from pathlib import Path

from psycopg import sql

from .database import Database

WORKLOADS = ("api", "attribution", "content", "collector")


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
