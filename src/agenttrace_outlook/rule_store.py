"""Durable pending/late source reassessment and idempotent decision updates."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from .contracts import Observation
from .errors import OutlookError
from .sender_rules import POLICY_VERSION, RuleAssessment, enrolled_sender, sha
from .state import StateStore


class RuleStore:
    def __init__(self, store: StateStore):
        self.store = store

    def snapshot(self, observation: Observation) -> dict[str, Any] | None:
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT payload,expires FROM snapshots WHERE message_id=?",
                (observation.message_id,),
            ).fetchone()
            if row and row[1] > self.store.clock().timestamp():
                result: dict[str, Any] = json.loads(row[0])
                return result
            return None

    def source(self, observation_id: int) -> dict[str, Any] | None:
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT payload FROM rule_sources WHERE observation_id=?", (observation_id,)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def assessment(self, observation_id: int, assessment: RuleAssessment) -> None:
        with self.store.transaction(lease=self.store.lease) as db:
            db.execute(
                "INSERT INTO rule_assessments VALUES (?,?,?) ON CONFLICT(observation_id) DO UPDATE SET payload=excluded.payload,assessed=excluded.assessed",
                (observation_id, assessment.model_dump_json(), self.store.clock().timestamp()),
            )

    def prepare(self) -> None:
        store = self.store
        with store.transaction(lease=store.lease) as db:
            source = store.config.sender_source
            enrollment = (
                sha(
                    {
                        **source.model_dump(
                            mode="json", exclude={"audit_identity", "refresh_seconds"}
                        ),
                        "audit_client_id": str(source.audit_identity.client_id),
                    }
                )
                if source
                else "disabled"
            )
            bound = db.execute(
                "SELECT value FROM metadata WHERE key='sender_enrollment'"
            ).fetchone()
            if bound and bound[0] != enrollment:
                raise OutlookError("sender_enrollment_changed_requires_review")
            db.execute(
                "INSERT OR IGNORE INTO metadata VALUES ('sender_enrollment',?)", (enrollment,)
            )
            policy = db.execute(
                "SELECT value FROM metadata WHERE key='sender_policy_version'"
            ).fetchone()
            if policy is None or policy[0] != POLICY_VERSION:
                db.execute(
                    "UPDATE work SET status='pending' WHERE status='completed' AND observation_id IN (SELECT current_observation FROM messages)"
                )
                db.execute(
                    "INSERT INTO metadata VALUES ('sender_policy_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (POLICY_VERSION,),
                )
            db.execute(
                "UPDATE rule_jobs SET stage='superseded' WHERE observation_id NOT IN (SELECT current_observation FROM messages) AND stage!='superseded'"
            )
            rows = db.execute(
                "SELECT o.id,o.payload,s.payload FROM observations o JOIN messages m ON m.current_observation=o.id JOIN snapshots s ON s.message_id=o.message_id LEFT JOIN rule_jobs j ON j.observation_id=o.id WHERE j.observation_id IS NULL AND s.expires>? LIMIT ?",
                (store.clock().timestamp(), store.config.batch_size),
            ).fetchall()
            for row in rows:
                observation = Observation.model_validate_json(row[1])
                snapshot = json.loads(row[2])
                source = store.config.sender_source
                eligible = source is not None and enrolled_sender(snapshot, source.mailbox_address)
                db.execute(
                    "INSERT INTO rule_jobs(observation_id,stage) VALUES (?,?)",
                    (row[0], "new" if eligible else "unavailable"),
                )
                db.execute(
                    "UPDATE work SET status='pending' WHERE observation_id=? AND status='completed'",
                    (row[0],),
                )
                if not eligible:
                    payload = {
                        "observed_version": observation.source_version,
                        "expires_at": (observation.observed_at + timedelta(days=7)).timestamp(),
                        "status": "unavailable",
                        "reason": "sender_source_not_enrolled_for_message",
                        "evidence_refs": [],
                    }
                    db.execute(
                        "INSERT INTO rule_sources VALUES (?,?,?, ?,?) ON CONFLICT(observation_id) DO NOTHING",
                        (
                            row[0],
                            json.dumps(payload),
                            "{}",
                            store.clock().timestamp(),
                            (observation.observed_at + timedelta(days=7)).timestamp(),
                        ),
                    )
            # Freshness expiry produces an explicit reassessment without a new
            # message version, even if the source is currently inaccessible.
            db.execute(
                "UPDATE work SET status='pending' WHERE status='completed' AND observation_id IN (SELECT a.observation_id FROM rule_assessments a JOIN rule_sources s ON s.observation_id=a.observation_id JOIN messages m ON m.current_observation=a.observation_id WHERE json_extract(s.payload,'$.expires_at')<=? AND a.assessed<json_extract(s.payload,'$.expires_at'))",
                (store.clock().timestamp(),),
            )
            # Explanation windows also advance for unavailable/non-enrolled sources.
            # Observation expiry is exactly observed_at + seven days; arithmetic
            # keeps subsecond precision without parsing timestamps through SQLite.
            initial_offset = timedelta(days=7, hours=-2).total_seconds()
            late_offset = timedelta(days=6).total_seconds()
            db.execute(
                "UPDATE work SET status='pending' WHERE status='completed' AND observation_id IN (SELECT o.id FROM observations o JOIN messages m ON m.current_observation=o.id JOIN rule_assessments a ON a.observation_id=o.id WHERE (? >= o.expires-? AND a.assessed < o.expires-?) OR (? > o.expires-? AND a.assessed <= o.expires-?))",
                (
                    store.clock().timestamp(),
                    initial_offset,
                    initial_offset,
                    store.clock().timestamp(),
                    late_offset,
                    late_offset,
                ),
            )

    def due(self) -> tuple[dict[str, Any], Observation, dict[str, Any]] | None:
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT j.*,o.payload AS observation,s.payload AS snapshot FROM rule_jobs j JOIN observations o ON o.id=j.observation_id JOIN messages m ON m.current_observation=o.id JOIN snapshots s ON s.message_id=o.message_id WHERE j.stage NOT IN ('unavailable','closed','blocked','superseded') AND j.due<=? AND s.expires>? ORDER BY j.due,j.observation_id LIMIT 1",
                (self.store.clock().timestamp(), self.store.clock().timestamp()),
            ).fetchone()
            if row is None:
                return None
            return (
                dict(row),
                Observation.model_validate_json(row["observation"]),
                json.loads(row["snapshot"]),
            )

    def update(
        self,
        job: dict[str, Any],
        *,
        stage: str,
        delay: int = 0,
        query_id: str | None = None,
        cursor: str | None = None,
        records: list[dict[str, Any]] | None = None,
        error: str | None = None,
        attempts: int = 0,
    ) -> None:
        with self.store.transaction(lease=self.store.lease) as db:
            changed = db.execute(
                "UPDATE rule_jobs SET stage=?,query_id=?,cursor=?,records=?,error=?,due=?,attempts=?,generation=generation+1 WHERE observation_id=? AND generation=?",
                (
                    stage,
                    query_id,
                    cursor,
                    json.dumps(records or []),
                    error,
                    self.store.clock().timestamp() + delay,
                    attempts,
                    job["observation_id"],
                    job["generation"],
                ),
            ).rowcount
            if changed != 1:
                raise OutlookError("stale_rule_source_job")

    def capture(
        self,
        job: dict[str, Any],
        observation: Observation,
        *,
        status: str,
        reason: str,
        refs: tuple[str, ...] = (),
        raw: dict[str, Any] | None = None,
        receipt_context: str = "unqualified",
    ) -> None:
        now = self.store.clock()
        payload = {
            "observed_version": observation.source_version,
            "status": status,
            "receipt_context": receipt_context,
            "reason": reason,
            "evidence_refs": list(refs),
            "expires_at": min(
                (now + timedelta(minutes=5)).timestamp(),
                (observation.observed_at + timedelta(days=7)).timestamp(),
            ),
        }
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT generation FROM rule_jobs WHERE observation_id=?", (job["observation_id"],)
            ).fetchone()
            if not row or row[0] != job["generation"]:
                raise OutlookError("stale_rule_source_job")
            old = db.execute(
                "SELECT raw_payload FROM rule_sources WHERE observation_id=?",
                (job["observation_id"],),
            ).fetchone()
            archive = json.loads(old[0]).get("captures", []) if old else []
            if raw:
                if len(archive) >= 1000:
                    raise OutlookError("source_capture_history_limit")
                archive.append({"captured_at": now.timestamp(), "data": raw})
            db.execute(
                "INSERT INTO rule_sources VALUES (?,?,?,?,?) ON CONFLICT(observation_id) DO UPDATE SET payload=excluded.payload,raw_payload=excluded.raw_payload,captured=excluded.captured,expires=excluded.expires",
                (
                    job["observation_id"],
                    json.dumps(payload),
                    json.dumps({"captures": archive}),
                    now.timestamp(),
                    min(
                        (now + timedelta(days=7)).timestamp(),
                        (observation.observed_at + timedelta(days=7)).timestamp(),
                    ),
                ),
            )
            db.execute(
                "UPDATE work SET status='pending' WHERE observation_id=? AND status='completed'",
                (job["observation_id"],),
            )

    def summary(self) -> dict[str, int | str]:
        with self.store.transaction(lease=self.store.lease) as db:
            return {
                "rules_profile": "corroborated_poc_ai_and_human_capable",
                "source_jobs": db.execute("SELECT count(*) FROM rule_jobs").fetchone()[0],
                "source_blocked": db.execute(
                    "SELECT count(*) FROM rule_jobs WHERE stage='blocked'"
                ).fetchone()[0],
                "source_pending": db.execute(
                    "SELECT count(*) FROM rule_jobs WHERE stage IN ('new','poll','records','sent')"
                ).fetchone()[0],
                "rule_assessments": db.execute("SELECT count(*) FROM rule_assessments").fetchone()[
                    0
                ],
            }

    def retry_failed(self) -> int:
        with self.store.transaction(lease=self.store.lease) as db:
            return db.execute(
                "UPDATE rule_jobs SET stage='new',query_id=NULL,cursor=NULL,records='[]',due=0,attempts=0,error=NULL,generation=generation+1 WHERE stage='blocked'"
            ).rowcount
