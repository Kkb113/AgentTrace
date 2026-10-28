"""Transactional durable inbox, fenced checkpoints and independent analysis dispatch."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from agenttrace_text_normalization import Extraction
from cryptography.hazmat.primitives.asymmetric import rsa
from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from agenttrace_foundation.database import Database

from .contracts import Enrollment, IngestionError, MessageSnapshot, SourceNotification, utc_now
from .protection import EvidenceCipher, seal_content


@dataclass(frozen=True)
class EventLease:
    event_ref: UUID
    source_ref: UUID
    receipt: UUID
    notification: SourceNotification
    attempts: int


@dataclass(frozen=True)
class CheckpointLease:
    source_ref: UUID
    partition_ref: UUID
    receipt: UUID
    generation: int
    cursor: str | None
    watermark: datetime | None


class IngestionStore:
    def __init__(self, database: Database, cipher: EvidenceCipher):
        self.database, self.cipher = database, cipher

    def enroll(
        self, enrollment: Enrollment, *, kind: str = "mailbox", alias: str = "synthetic-pilot"
    ) -> None:
        if self.database.settings.database_user != "agenttrace":
            raise IngestionError("operator_enrollment_identity_required")
        binding = self.cipher.digest(
            (kind + ":" + str(enrollment.tenant_id) + ":" + str(enrollment.mailbox_id)).encode()
        )
        scope = self.cipher.seal(
            {
                "tenant_id": str(enrollment.tenant_id),
                "mailbox_id": str(enrollment.mailbox_id),
                "folders": list(enrollment.folder_ids),
            },
            context="scope:" + str(enrollment.source_ref),
        )
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT binding_digest FROM ingest_sources WHERE source_ref=%s",
                (enrollment.source_ref,),
            ).fetchone()
            if current and current["binding_digest"] != binding:
                raise IngestionError("source_enrollment_binding_conflict")
            connection.execute(
                "INSERT INTO ingest_sources(source_ref,source_kind,source_alias,binding_digest,scope_cipher) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(source_ref) DO NOTHING",
                (enrollment.source_ref, kind, alias, binding, scope),
            )
            for role in (
                "agenttrace_collector",
                "agenttrace_api",
                "agenttrace_attribution",
                "agenttrace_content",
            ):
                connection.execute(
                    "INSERT INTO ingest_source_acl(source_ref,db_role) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (enrollment.source_ref, role),
                )

    def _persist(self, connection: Connection[DictRow], notification: SourceNotification) -> bool:
        encrypted = self.cipher.seal(
            json.loads(notification.model_dump_json()),
            context="event:" + str(notification.event_ref),
        )
        result = connection.execute(
            "INSERT INTO ingest_events(event_ref,source_ref,kind,locator_cipher,event_time,received_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_ref) DO NOTHING",
            (
                notification.event_ref,
                notification.source_ref,
                notification.change,
                encrypted,
                notification.event_time,
                notification.received_at,
                notification.received_at + timedelta(days=7),
            ),
        )
        return result.rowcount == 1

    def accept(self, notifications: list[SourceNotification]) -> int:
        with self.database.connect() as connection:
            # Returning from this method means this whole accepted batch committed.
            return sum(self._persist(connection, item) for item in notifications)

    def claim(
        self,
        source_ref: UUID,
        *,
        now: datetime | None = None,
        visibility_seconds: int = 90,
        maximum_attempts: int = 5,
    ) -> EventLease | None:
        instant = now or utc_now()
        if not 1 <= visibility_seconds <= 300:
            raise ValueError("invalid_ingestion_visibility")
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE ingest_events SET state='poison',last_error_code='maximum_attempts_exceeded',receipt=NULL WHERE source_ref=%s AND state IN ('pending','retry','leased') AND visible_at<=%s AND (attempts>=%s OR expires_at<=%s)",
                (source_ref, instant, maximum_attempts, instant),
            )
            row = connection.execute(
                "SELECT * FROM ingest_events WHERE source_ref=%s AND state IN ('pending','retry','leased') AND visible_at<=%s AND expires_at>%s ORDER BY received_at,event_ref FOR UPDATE SKIP LOCKED LIMIT 1",
                (source_ref, instant, instant),
            ).fetchone()
            if row is None:
                return None
            receipt = uuid4()
            connection.execute(
                "UPDATE ingest_events SET state='leased',receipt=%s,visible_at=%s,attempts=attempts+1 WHERE event_ref=%s",
                (receipt, instant + timedelta(seconds=visibility_seconds), row["event_ref"]),
            )
        try:
            value = self.cipher.open(
                bytes(row["locator_cipher"]), context="event:" + str(row["event_ref"])
            )
            return EventLease(
                row["event_ref"],
                source_ref,
                receipt,
                SourceNotification.model_validate(value),
                row["attempts"] + 1,
            )
        except Exception:
            with self.database.connect() as connection:
                connection.execute(
                    "UPDATE ingest_events SET state='poison',last_error_code='invalid_encrypted_event',receipt=NULL WHERE event_ref=%s AND receipt=%s",
                    (row["event_ref"], receipt),
                )
            raise IngestionError("invalid_encrypted_event") from None

    def _fence(self, connection: Connection[DictRow], lease: EventLease) -> None:
        row = connection.execute(
            "SELECT event_ref FROM ingest_events WHERE event_ref=%s AND source_ref=%s AND receipt=%s AND state='leased' AND visible_at>%s AND expires_at>now() FOR UPDATE",
            (lease.event_ref, lease.source_ref, lease.receipt, utc_now()),
        ).fetchone()
        if row is None:
            raise IngestionError("ingestion_lease_lost")

    def _ack(self, connection: Connection[DictRow], lease: EventLease) -> None:
        connection.execute(
            "UPDATE ingest_events SET state='processed',receipt=NULL,last_error_code=NULL WHERE event_ref=%s AND receipt=%s",
            (lease.event_ref, lease.receipt),
        )

    def retry(self, lease: EventLease, error: IngestionError) -> None:
        delay = max(error.retry_after, min(300, 2 ** min(lease.attempts, 8)))
        with self.database.connect() as connection:
            self._fence(connection, lease)
            connection.execute(
                "UPDATE ingest_events SET state=%s,last_error_code=%s,visible_at=%s,receipt=NULL WHERE event_ref=%s",
                (
                    "retry" if error.retryable else "poison",
                    error.code,
                    utc_now() + timedelta(seconds=delay),
                    lease.event_ref,
                ),
            )

    def complete_message(
        self,
        lease: EventLease,
        snapshot: MessageSnapshot,
        extraction: Extraction,
        public_key: rsa.RSAPublicKey,
    ) -> UUID:
        message_ref = self.cipher.reference(str(lease.source_ref), snapshot.immutable_id)
        version_ref = self.cipher.reference(str(message_ref), snapshot.change_key)
        folder_ref = self.cipher.reference(str(lease.source_ref), snapshot.parent_folder_id)
        locator = self.cipher.seal(
            {
                "immutable_id": snapshot.immutable_id,
                "internet_message_id": snapshot.internet_message_id,
            },
            context="message:" + str(message_ref),
        )
        summary = extraction.summary() | {"is_draft": snapshot.is_draft}
        content_digest = (
            self.cipher.digest((snapshot.body or "").encode())
            if snapshot.body is not None
            else None
        )
        expires = utc_now() + timedelta(minutes=15)
        capsule = seal_content(
            {
                "authored_text": extraction.authored_text,
                "normalized_text": extraction.normalized_text,
                "regions": [asdict(r) for r in extraction.regions],
                "offsets": [asdict(o) for o in extraction.offsets],
                "summary": summary,
            },
            public_key,
            version_ref=version_ref,
            expires_at=expires,
        )
        with self.database.connect() as connection:
            self._fence(connection, lease)
            connection.execute(
                "INSERT INTO ingest_copies(message_ref,source_ref,copy_key,locator_cipher,folder_ref,modified_at,copy_role,delivery_ref) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(message_ref) DO NOTHING",
                (
                    message_ref,
                    lease.source_ref,
                    str(message_ref),
                    locator,
                    folder_ref,
                    snapshot.modified_at,
                    snapshot.copy_role,
                    self.cipher.reference(
                        str(lease.source_ref), "delivery-candidate:" + snapshot.internet_message_id
                    )
                    if snapshot.internet_message_id
                    else None,
                ),
            )
            existing = connection.execute(
                "SELECT current_version,modified_at FROM ingest_copies WHERE message_ref=%s FOR UPDATE",
                (message_ref,),
            ).fetchone()
            if (
                existing
                and existing["modified_at"] > snapshot.modified_at
                and existing["current_version"]
            ):
                self._ack(connection, lease)
                return UUID(str(existing["current_version"]))
            if existing and existing["current_version"] == version_ref:
                connection.execute(
                    "UPDATE ingest_copies SET folder_ref=%s,observed_at=%s,visibility='current' WHERE message_ref=%s",
                    (folder_ref, utc_now(), message_ref),
                )
                self._ack(connection, lease)
                return version_ref
            connection.execute(
                "UPDATE ingest_versions SET obsolete=true WHERE message_ref=%s AND version_ref<>%s",
                (message_ref, version_ref),
            )
            connection.execute(
                "UPDATE ingest_dispatch SET state='superseded',receipt=NULL WHERE version_ref IN (SELECT version_ref FROM ingest_versions WHERE message_ref=%s AND obsolete=true)",
                (message_ref,),
            )
            connection.execute(
                "DELETE FROM ingest_content_inputs WHERE version_ref IN (SELECT version_ref FROM ingest_versions WHERE message_ref=%s AND obsolete=true)",
                (message_ref,),
            )
            connection.execute(
                "INSERT INTO ingest_versions(version_ref,source_ref,message_ref,change_digest,content_digest,summary,source_event_time) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(version_ref) DO NOTHING",
                (
                    version_ref,
                    lease.source_ref,
                    message_ref,
                    self.cipher.digest(snapshot.change_key.encode()),
                    content_digest,
                    Jsonb(summary),
                    lease.notification.event_time or snapshot.source_event_at,
                ),
            )
            connection.execute(
                "UPDATE ingest_copies SET current_version=%s,modified_at=%s,observed_at=%s,folder_ref=%s,copy_role=%s,visibility='current' WHERE message_ref=%s",
                (
                    version_ref,
                    snapshot.modified_at,
                    utc_now(),
                    folder_ref,
                    snapshot.copy_role,
                    message_ref,
                ),
            )
            for axis in ("agent", "content"):
                connection.execute(
                    "INSERT INTO ingest_dispatch(version_ref,source_ref,axis) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (version_ref, lease.source_ref, axis),
                )
            if extraction.status == "extracted" and extraction.authored_text:
                connection.execute(
                    "INSERT INTO ingest_content_inputs(version_ref,source_ref,capsule,expires_at) VALUES (%s,%s,%s,%s) ON CONFLICT(version_ref) DO NOTHING",
                    (version_ref, lease.source_ref, capsule, expires),
                )
            self._ack(connection, lease)
        return version_ref

    def unavailable_message(
        self, lease: EventLease, immutable_id: str, *, moved: bool = False
    ) -> None:
        ref = self.cipher.reference(str(lease.source_ref), immutable_id)
        with self.database.connect() as connection:
            self._fence(connection, lease)
            connection.execute(
                "UPDATE ingest_copies SET visibility=%s,observed_at=%s WHERE message_ref=%s",
                ("moved_out_of_scope" if moved else "deleted_or_unavailable", utc_now(), ref),
            )
            connection.execute(
                "UPDATE ingest_dispatch SET state='superseded',receipt=NULL WHERE version_ref IN (SELECT version_ref FROM ingest_versions WHERE message_ref=%s)",
                (ref,),
            )
            connection.execute(
                "DELETE FROM ingest_content_inputs WHERE version_ref IN (SELECT version_ref FROM ingest_versions WHERE message_ref=%s)",
                (ref,),
            )
            self._ack(connection, lease)

    def gap(
        self,
        source_ref: UUID,
        reason: str,
        *,
        partition_ref: UUID | None = None,
        started_at: datetime | None = None,
        known_lost: int | None = None,
    ) -> UUID:
        ref = uuid4()
        with self.database.connect() as connection:
            current = connection.execute(
                "SELECT gap_ref FROM ingest_gaps WHERE source_ref=%s AND partition_ref IS NOT DISTINCT FROM %s AND reason_code=%s AND disposition='open' LIMIT 1",
                (source_ref, partition_ref, reason),
            ).fetchone()
            if current:
                return UUID(str(current["gap_ref"]))
            connection.execute(
                "INSERT INTO ingest_gaps(gap_ref,source_ref,partition_ref,started_at,reason_code,disposition,known_lost_events) VALUES (%s,%s,%s,%s,%s,'open',%s)",
                (ref, source_ref, partition_ref, started_at or utc_now(), reason, known_lost),
            )
        return ref

    def health(self, source_ref: UUID) -> dict[str, Any]:
        with self.database.connect() as connection:
            exists = connection.execute(
                "SELECT source_alias FROM ingest_sources WHERE source_ref=%s", (source_ref,)
            ).fetchone()
            if exists is None:
                raise IngestionError("source_not_enrolled")
            events = connection.execute(
                "SELECT state,count(*) AS count,min(received_at) AS oldest FROM ingest_events WHERE source_ref=%s GROUP BY state",
                (source_ref,),
            ).fetchall()
            checkpoints = connection.execute(
                "SELECT coverage,reason_code,last_success,next_attempt,generation FROM ingest_checkpoints WHERE source_ref=%s ORDER BY partition_ref",
                (source_ref,),
            ).fetchall()
            subscriptions = connection.execute(
                "SELECT state,expires_at FROM ingest_subscriptions WHERE source_ref=%s",
                (source_ref,),
            ).fetchall()
            dispatch = connection.execute(
                "SELECT axis,state,count(*) AS count FROM ingest_dispatch WHERE source_ref=%s GROUP BY axis,state",
                (source_ref,),
            ).fetchall()
            gaps = connection.execute(
                "SELECT reason_code,disposition,known_lost_events FROM ingest_gaps WHERE source_ref=%s",
                (source_ref,),
            ).fetchall()
            inventory = connection.execute(
                "SELECT visibility,count(*) AS count FROM ingest_copies WHERE source_ref=%s GROUP BY visibility",
                (source_ref,),
            ).fetchall()
            transport_poison = connection.execute(
                "SELECT count(*) AS count,min(received_at) AS oldest FROM ingest_transport_poison WHERE source_ref=%s",
                (source_ref,),
            ).fetchone()
            messages = connection.execute(
                "SELECT message_ref,current_version,visibility,copy_role,delivery_ref FROM ingest_copies WHERE source_ref=%s ORDER BY message_ref",
                (source_ref,),
            ).fetchall()
            return {
                "source_alias": exists["source_alias"],
                "events": [
                    {
                        "state": r["state"],
                        "count": r["count"],
                        "oldest_age_seconds": max(
                            0, int((utc_now() - r["oldest"]).total_seconds())
                        ),
                    }
                    for r in events
                ],
                "checkpoints": [
                    {
                        **r,
                        "last_success": r["last_success"].isoformat()
                        if r["last_success"]
                        else None,
                        "next_attempt": r["next_attempt"].isoformat(),
                    }
                    for r in checkpoints
                ],
                "subscriptions": [
                    {
                        "state": "expired" if r["expires_at"] <= utc_now() else r["state"],
                        "expires_at": r["expires_at"].isoformat(),
                    }
                    for r in subscriptions
                ],
                "analysis_work": dispatch,
                "gaps": gaps,
                "inventory": inventory,
                "messages": [
                    {
                        "message_ref": str(r["message_ref"]),
                        "version_ref": str(r["current_version"]) if r["current_version"] else None,
                        "visibility": r["visibility"],
                        "copy_role": r["copy_role"],
                        "delivery_candidate_ref": str(r["delivery_ref"])
                        if r["delivery_ref"]
                        else None,
                        "delivery_link": "unverified_header_group_only",
                    }
                    for r in messages
                ],
                "native_poison_count": transport_poison["count"] if transport_poison else 0,
                "agent_attribution": "not_established_by_ingestion",
                "content_scorer": "not_installed",
            }

    def claim_checkpoint(self, source_ref: UUID, partition_ref: UUID) -> CheckpointLease | None:
        receipt = uuid4()
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO ingest_checkpoints(source_ref,partition_ref) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                (source_ref, partition_ref),
            )
            row = connection.execute(
                "UPDATE ingest_checkpoints SET lease=%s,lease_until=now()+interval '90 seconds' WHERE source_ref=%s AND partition_ref=%s AND next_attempt<=now() AND (lease_until IS NULL OR lease_until<=now()) RETURNING *",
                (receipt, source_ref, partition_ref),
            ).fetchone()
        if row is None:
            return None
        cursor = None
        if row["cursor_cipher"]:
            try:
                cursor = self.cipher.open(
                    bytes(row["cursor_cipher"]), context="cursor:" + str(partition_ref)
                )["cursor"]
            except Exception:
                lease = CheckpointLease(
                    source_ref, partition_ref, receipt, row["generation"], None, row["watermark"]
                )
                self.fail_checkpoint(lease, IngestionError("source_cursor_invalid"), reset=True)
                raise IngestionError("source_cursor_invalid") from None
        return CheckpointLease(
            source_ref, partition_ref, receipt, row["generation"], cursor, row["watermark"]
        )

    def _checkpoint_fence(self, connection: Connection[DictRow], lease: CheckpointLease) -> None:
        row = connection.execute(
            "SELECT source_ref FROM ingest_checkpoints WHERE source_ref=%s AND partition_ref=%s AND lease=%s AND generation=%s AND lease_until>now() FOR UPDATE",
            (lease.source_ref, lease.partition_ref, lease.receipt, lease.generation),
        ).fetchone()
        if row is None:
            raise IngestionError("checkpoint_lease_lost")

    def commit_page(
        self,
        lease: CheckpointLease,
        notifications: list[SourceNotification],
        cursor: str,
        *,
        final: bool,
        watermark: datetime | None = None,
    ) -> int:
        if any(n.source_ref != lease.source_ref for n in notifications):
            raise IngestionError("checkpoint_source_mismatch")
        encrypted = self.cipher.seal(
            {"cursor": cursor}, context="cursor:" + str(lease.partition_ref)
        )
        with self.database.connect() as connection:
            self._checkpoint_fence(connection, lease)
            count = sum(self._persist(connection, n) for n in notifications)
            connection.execute(
                "UPDATE ingest_checkpoints SET cursor_cipher=%s,watermark=COALESCE(%s,watermark),coverage=%s,reason_code=%s,last_success=CASE WHEN %s THEN now() ELSE last_success END,lease=NULL,lease_until=NULL,next_attempt=now() WHERE source_ref=%s AND partition_ref=%s",
                (
                    encrypted,
                    watermark,
                    "current" if final else "catching_up",
                    "delta_current" if final else "next_page_pending",
                    final,
                    lease.source_ref,
                    lease.partition_ref,
                ),
            )
            if final:
                connection.execute(
                    "UPDATE ingest_gaps SET disposition='recovered_current_state',ended_at=now() WHERE source_ref=%s AND partition_ref=%s AND disposition='open'",
                    (lease.source_ref, lease.partition_ref),
                )
        return count

    def fail_checkpoint(
        self, lease: CheckpointLease, error: IngestionError, *, reset: bool = False
    ) -> None:
        with self.database.connect() as connection:
            self._checkpoint_fence(connection, lease)
            connection.execute(
                "UPDATE ingest_checkpoints SET cursor_cipher=CASE WHEN %s THEN NULL ELSE cursor_cipher END,generation=generation+CASE WHEN %s THEN 1 ELSE 0 END,coverage=%s,reason_code=%s,lease=NULL,lease_until=NULL,next_attempt=now()+make_interval(secs=>%s) WHERE source_ref=%s AND partition_ref=%s",
                (
                    reset,
                    reset,
                    "resync_required" if reset else "degraded",
                    error.code,
                    max(1, error.retry_after),
                    lease.source_ref,
                    lease.partition_ref,
                ),
            )
            connection.execute(
                "INSERT INTO ingest_gaps(gap_ref,source_ref,partition_ref,started_at,reason_code,disposition) SELECT %s,%s,%s,COALESCE(last_success,now()),%s,'open' FROM ingest_checkpoints WHERE source_ref=%s AND partition_ref=%s AND NOT EXISTS(SELECT 1 FROM ingest_gaps WHERE source_ref=%s AND partition_ref=%s AND reason_code=%s AND disposition='open')",
                (
                    uuid4(),
                    lease.source_ref,
                    lease.partition_ref,
                    error.code,
                    lease.source_ref,
                    lease.partition_ref,
                    lease.source_ref,
                    lease.partition_ref,
                    error.code,
                ),
            )

    def wait_checkpoint(self, lease: CheckpointLease, *, reason: str, seconds: int) -> None:
        with self.database.connect() as connection:
            self._checkpoint_fence(connection, lease)
            connection.execute(
                "UPDATE ingest_checkpoints SET coverage='catching_up',reason_code=%s,lease=NULL,lease_until=NULL,next_attempt=now()+make_interval(secs=>%s) WHERE source_ref=%s AND partition_ref=%s",
                (reason, min(3600, max(1, seconds)), lease.source_ref, lease.partition_ref),
            )

    def save_subscription(
        self,
        source_ref: UUID,
        native_id: str,
        expires_at: datetime,
        *,
        state: str = "active",
        folder_id: str | None = None,
    ) -> UUID:
        ref = self.cipher.reference(str(source_ref), "subscription:" + native_id)
        encrypted = self.cipher.seal(
            {"id": native_id, "folder_id": folder_id}, context="subscription:" + str(ref)
        )
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO ingest_subscriptions(subscription_ref,source_ref,locator_cipher,expires_at,state) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(subscription_ref) DO UPDATE SET expires_at=EXCLUDED.expires_at,state=EXCLUDED.state,updated_at=now()",
                (ref, source_ref, encrypted, expires_at, state),
            )
        return ref

    def subscriptions(self, source_ref: UUID) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ingest_subscriptions WHERE source_ref=%s", (source_ref,)
            ).fetchall()
        return [
            {
                "id": self.cipher.open(
                    bytes(r["locator_cipher"]), context="subscription:" + str(r["subscription_ref"])
                )["id"],
                "state": r["state"],
                "folder_id": self.cipher.open(
                    bytes(r["locator_cipher"]), context="subscription:" + str(r["subscription_ref"])
                ).get("folder_id"),
                "expires_at": r["expires_at"],
            }
            for r in rows
        ]

    def complete_lifecycle(self, lease: EventLease) -> None:
        states = {
            "reauthorizationRequired": "reauthorization_required",
            "subscriptionRemoved": "removed",
            "missed": "renewal_required",
        }
        with self.database.connect() as connection:
            self._fence(connection, lease)
            connection.execute(
                "UPDATE ingest_subscriptions SET state=%s,updated_at=now() WHERE subscription_ref=%s",
                (
                    states[lease.notification.change],
                    self.cipher.reference(
                        str(lease.source_ref), "subscription:" + lease.notification.subscription_ref
                    ),
                ),
            )
            connection.execute(
                "UPDATE ingest_checkpoints SET coverage='degraded',reason_code='subscription_lifecycle_gap',next_attempt=now() WHERE source_ref=%s",
                (lease.source_ref,),
            )
            connection.execute(
                "INSERT INTO ingest_gaps(gap_ref,source_ref,started_at,reason_code,disposition) VALUES (%s,%s,%s,'subscription_lifecycle_gap','open')",
                (
                    uuid4(),
                    lease.source_ref,
                    lease.notification.event_time or lease.notification.received_at,
                ),
            )
            self._ack(connection, lease)

    def replay(self, source_ref: UUID, event_ref: UUID) -> bool:
        with self.database.connect() as connection:
            return (
                connection.execute(
                    "UPDATE ingest_events SET state='pending',attempts=0,last_error_code=NULL,visible_at=now(),receipt=NULL WHERE event_ref=%s AND source_ref=%s AND state='poison' AND expires_at>now()",
                    (event_ref, source_ref),
                ).rowcount
                == 1
            )

    def purge(self) -> dict[str, int]:
        if self.database.settings.database_user != "agenttrace":
            raise IngestionError("operator_retention_identity_required")
        counts = {}
        with self.database.connect() as connection:
            for table in (
                "ingest_content_inputs",
                "ingest_events",
                "ingest_audit_events",
                "ingest_transport_poison",
            ):
                counts[table] = connection.execute(
                    "DELETE FROM " + table + " WHERE expires_at<=now()"
                ).rowcount
            # Remove dependent work before versions, then orphaned locators. Checkpoints
            # retain only encrypted operational cursors while enrollment is active.
            connection.execute(
                "DELETE FROM ingest_content_inputs WHERE version_ref IN(SELECT version_ref FROM ingest_versions WHERE expires_at<=now())"
            )
            connection.execute(
                "DELETE FROM ingest_dispatch WHERE version_ref IN(SELECT version_ref FROM ingest_versions WHERE expires_at<=now())"
            )
            connection.execute(
                "UPDATE ingest_copies SET current_version=NULL WHERE current_version IN(SELECT version_ref FROM ingest_versions WHERE expires_at<=now())"
            )
            counts["ingest_versions"] = connection.execute(
                "DELETE FROM ingest_versions WHERE expires_at<=now()"
            ).rowcount
            counts["ingest_copies"] = connection.execute(
                "DELETE FROM ingest_copies WHERE current_version IS NULL AND observed_at<=now()-interval '30 days'"
            ).rowcount
            counts["ingest_gaps"] = connection.execute(
                "DELETE FROM ingest_gaps WHERE started_at<=now()-interval '30 days'"
            ).rowcount
        return counts

    def quarantine_transport(self, source_ref: UUID, payload: bytes, reason: str) -> None:
        digest = self.cipher.digest(payload)
        with self.database.connect() as connection:
            connection.execute(
                "INSERT INTO ingest_transport_poison(event_ref,source_ref,payload_digest,reason_code) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    self.cipher.reference(str(source_ref), "native-poison:" + digest),
                    source_ref,
                    digest,
                    reason,
                ),
            )
            connection.execute(
                "UPDATE ingest_gaps SET disposition='unrecoverable',ended_at=now() WHERE source_ref=%s AND reason_code='native_notification_validation_failed' AND disposition='open'",
                (source_ref,),
            )
