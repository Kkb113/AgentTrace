"""Development PostgreSQL queue. Azure Storage Queue parity is not implied."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID, uuid4

from agenttrace_contracts import DetectionJob, utc_now
from psycopg.types.json import Jsonb

from .database import Database

QueueName = Literal["agent-evidence", "content-analysis"]


@dataclass(frozen=True)
class Lease:
    job_id: UUID
    receipt: UUID
    payload: DetectionJob
    attempts: int


class DetectionQueue(Protocol):
    def enqueue(self, payload: DetectionJob, key: str) -> UUID: ...
    def receive(
        self, *, now: datetime | None = None, visibility_seconds: int = 30
    ) -> Lease | None: ...
    def acknowledge(self, lease: Lease, *, now: datetime | None = None) -> bool: ...


class DevelopmentQueue:
    def __init__(self, database: Database, name: QueueName, *, maximum_attempts: int = 3):
        if name not in {"agent-evidence", "content-analysis"} or not 1 <= maximum_attempts <= 10:
            raise ValueError("invalid_development_queue_configuration")
        self.database, self.name, self.maximum_attempts = database, name, maximum_attempts

    def enqueue(self, payload: DetectionJob, key: str) -> UUID:
        if not 1 <= len(key) <= 128:
            raise ValueError("invalid_idempotency_key")
        with self.database.connect() as connection:
            row = connection.execute(
                "INSERT INTO detection_jobs(job_id,queue_name,idempotency_key,payload,visible_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(queue_name,idempotency_key) "
                "DO UPDATE SET idempotency_key=EXCLUDED.idempotency_key "
                "RETURNING job_id,payload",
                (uuid4(), self.name, key, Jsonb(payload.model_dump(mode="json")), utc_now()),
            ).fetchone()
            assert row is not None
            if DetectionJob.model_validate(row["payload"]) != payload:
                raise ValueError("conflicting_idempotency_key")
            return UUID(str(row["job_id"]))

    def receive(self, *, now: datetime | None = None, visibility_seconds: int = 30) -> Lease | None:
        if not 1 <= visibility_seconds <= 3600:
            raise ValueError("invalid_visibility_timeout")
        observed = now or utc_now()
        with self.database.connect() as connection:
            for _ in range(100):
                row = connection.execute(
                    "SELECT * FROM detection_jobs WHERE queue_name=%s AND state='pending' "
                    "AND visible_at<=%s ORDER BY visible_at,job_id FOR UPDATE SKIP LOCKED LIMIT 1",
                    (self.name, observed),
                ).fetchone()
                if row is None:
                    return None
                if row["attempts"] >= self.maximum_attempts:
                    connection.execute(
                        "UPDATE detection_jobs SET state='poison',receipt=NULL,last_error_code="
                        "'maximum_attempts_exceeded' WHERE job_id=%s",
                        (row["job_id"],),
                    )
                    continue
                receipt = uuid4()
                connection.execute(
                    "UPDATE detection_jobs SET receipt=%s,visible_at=%s,attempts=attempts+1 "
                    "WHERE job_id=%s",
                    (receipt, observed + timedelta(seconds=visibility_seconds), row["job_id"]),
                )
                return Lease(
                    UUID(str(row["job_id"])),
                    receipt,
                    DetectionJob.model_validate(row["payload"]),
                    int(row["attempts"]) + 1,
                )
        return None

    def acknowledge(self, lease: Lease, *, now: datetime | None = None) -> bool:
        with self.database.connect() as connection:
            result = connection.execute(
                "UPDATE detection_jobs SET state='completed',receipt=NULL "
                "WHERE job_id=%s AND queue_name=%s AND receipt=%s AND state='pending' AND visible_at>%s",
                (lease.job_id, self.name, lease.receipt, now or utc_now()),
            )
            return result.rowcount == 1

    def retry(self, lease: Lease, *, delay_seconds: int = 1) -> bool:
        if not 0 <= delay_seconds <= 3600:
            raise ValueError("invalid_retry_delay")
        with self.database.connect() as connection:
            result = connection.execute(
                "UPDATE detection_jobs SET receipt=NULL,visible_at=%s,last_error_code='worker_retry' "
                "WHERE job_id=%s AND queue_name=%s AND receipt=%s AND state='pending' AND visible_at>%s",
                (
                    utc_now() + timedelta(seconds=delay_seconds),
                    lease.job_id,
                    self.name,
                    lease.receipt,
                    utc_now(),
                ),
            )
            return result.rowcount == 1
