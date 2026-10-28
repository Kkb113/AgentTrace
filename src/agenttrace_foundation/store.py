"""Atomic result persistence and job acknowledgement in the development adapter."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from agenttrace_contracts import DetectionDecision, DetectionFindings, utc_now
from psycopg.types.json import Jsonb

from .database import Database
from .queue import Lease, QueueName


class DecisionStore:
    def __init__(self, database: Database):
        self.database = database

    def complete(
        self, queue: QueueName, lease: Lease, findings: DetectionFindings
    ) -> DetectionDecision | None:
        if queue != "agent-evidence":
            raise ValueError("content_worker_cannot_complete_agent_decisions")
        with self.database.connect() as connection:
            active = connection.execute(
                "SELECT job_id FROM detection_jobs WHERE job_id=%s AND queue_name=%s "
                "AND receipt=%s AND state='pending' AND visible_at>%s FOR UPDATE",
                (lease.job_id, queue, lease.receipt, utc_now()),
            ).fetchone()
            if active is None:
                return None
            decision = DetectionDecision(
                decision_id=uuid5(NAMESPACE_URL, "agenttrace-local-job:" + str(lease.job_id)),
                message_ref=lease.payload.message_ref,
                observed_at=utc_now(),
                validation_basis="authored_contract_example",
                findings=findings,
            )
            connection.execute(
                "INSERT INTO detection_decisions(decision_id,job_id,decision) VALUES (%s,%s,%s)",
                (decision.decision_id, lease.job_id, Jsonb(decision.model_dump(mode="json"))),
            )
            connection.execute(
                "UPDATE detection_jobs SET state='completed',receipt=NULL WHERE job_id=%s",
                (lease.job_id,),
            )
            return decision

    def get(self, decision_id: UUID) -> DetectionDecision | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT decision FROM detection_decisions WHERE decision_id=%s AND expires_at>%s",
                (decision_id, utc_now()),
            ).fetchone()
            return (
                None
                if row is None
                else DetectionDecision.model_validate_json(json.dumps(row["decision"]))
            )

    def heartbeat(self, component: Literal["attribution", "content"]) -> None:
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO component_health(component,observed_at) VALUES (%s,%s) "
                "ON CONFLICT(component) DO UPDATE SET observed_at=EXCLUDED.observed_at",
                (component, utc_now()),
            )

    def role_healthy(self, component: Literal["attribution", "content"]) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT component FROM component_health WHERE component=%s AND observed_at>%s",
                (component, utc_now() - timedelta(seconds=30)),
            ).fetchone()
            return row is not None
