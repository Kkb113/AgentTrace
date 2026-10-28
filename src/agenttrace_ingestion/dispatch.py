"""Version-fenced independent work queues for later attribution and content engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from agenttrace_foundation.database import Database

from .contracts import Axis, IngestionError


@dataclass(frozen=True)
class AnalysisLease:
    source_ref: UUID
    version_ref: UUID
    axis: Axis
    receipt: UUID


class AnalysisQueue:
    def __init__(self, database: Database):
        self.database = database

    def claim(self, source_ref: UUID, axis: Axis) -> AnalysisLease | None:
        receipt = uuid4()
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT d.version_ref FROM ingest_dispatch d JOIN ingest_versions v USING(version_ref) JOIN ingest_copies c ON c.current_version=v.version_ref WHERE d.source_ref=%s AND d.axis=%s AND (d.state='pending' OR (d.state='leased' AND d.lease_until<=now())) AND v.expires_at>now() AND NOT v.obsolete FOR UPDATE OF d SKIP LOCKED LIMIT 1",
                (source_ref, axis),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE ingest_dispatch SET state='leased',receipt=%s,lease_until=now()+interval '60 seconds' WHERE version_ref=%s AND axis=%s",
                (receipt, row["version_ref"], axis),
            )
            return AnalysisLease(source_ref, row["version_ref"], axis, receipt)

    def content_input(self, lease: AnalysisLease) -> bytes | None:
        if lease.axis != "content":
            raise IngestionError("content_axis_required")
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT i.capsule FROM ingest_content_inputs i JOIN ingest_dispatch d USING(version_ref,source_ref) WHERE i.version_ref=%s AND d.axis='content' AND d.receipt=%s AND d.state='leased' AND d.lease_until>now() AND i.expires_at>now()",
                (lease.version_ref, lease.receipt),
            ).fetchone()
            return bytes(row["capsule"]) if row else None

    def complete(self, lease: AnalysisLease) -> None:
        # Actual engine results must be committed by their future ledger transaction.
        # This method only acknowledges analysis work; it creates no detection verdict.
        with self.database.connect() as connection:
            updated = connection.execute(
                "UPDATE ingest_dispatch d SET state='completed',receipt=NULL,lease_until=NULL WHERE d.source_ref=%s AND d.version_ref=%s AND d.axis=%s AND d.receipt=%s AND d.state='leased' AND d.lease_until>now() AND EXISTS(SELECT 1 FROM ingest_copies c WHERE c.current_version=d.version_ref)",
                (lease.source_ref, lease.version_ref, lease.axis, lease.receipt),
            ).rowcount
            if updated != 1:
                raise IngestionError("analysis_version_or_lease_lost")

    def inventory(self, source_ref: UUID) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT message_ref,current_version,visibility FROM ingest_copies WHERE source_ref=%s ORDER BY message_ref",
                (source_ref,),
            ).fetchall()
