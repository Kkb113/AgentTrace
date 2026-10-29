"""Single-host SQLite transactions, lease fencing, versioned decisions and preview outbox."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from .config import RuntimeConfig
from .contracts import Decision, Observation
from .eligibility import require_annotation_eligible
from .errors import OutlookError
from .locking import ProcessLock

SCHEMA = (
    "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE lease (id INTEGER PRIMARY KEY CHECK(id=1), owner TEXT NOT NULL, generation INTEGER NOT NULL, expires REAL NOT NULL)",
    "CREATE TABLE observations (id INTEGER PRIMARY KEY, message_id TEXT NOT NULL, source_version TEXT NOT NULL, input_hash TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL, UNIQUE(message_id,source_version))",
    "CREATE TABLE messages (message_id TEXT PRIMARY KEY, current_observation INTEGER NOT NULL REFERENCES observations(id), decision_version INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE work (observation_id INTEGER PRIMARY KEY REFERENCES observations(id), status TEXT NOT NULL CHECK(status IN ('pending','retry','completed','superseded','dead_letter')), attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0, error_code TEXT)",
    "CREATE TABLE decisions (id INTEGER PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(message_id), version INTEGER NOT NULL, observation_id INTEGER NOT NULL REFERENCES observations(id), payload TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, UNIQUE(message_id,version))",
    "CREATE TABLE outbox (decision_id INTEGER PRIMARY KEY REFERENCES decisions(id), status TEXT NOT NULL CHECK(status IN ('preview','pending','superseded','failed')), category TEXT NOT NULL CHECK(category IN ('AI Agent','Human','Unknown')))",
    "CREATE INDEX work_due ON work(status,next_attempt)",
)
SCHEMA_DIGEST = hashlib.sha256("\n".join(SCHEMA).encode()).hexdigest()


@dataclass(frozen=True)
class Lease:
    owner: str
    generation: int


def utc_now() -> datetime:
    return datetime.now(UTC)


class StateStore:
    def __init__(self, config: RuntimeConfig, *, clock: Callable[[], datetime] = utc_now):
        if config.mode != "dry_run":
            raise OutlookError("category_application_not_enabled")
        self.config, self.clock = config, clock
        self._connection: sqlite3.Connection | None = None
        self._lock: ProcessLock | None = None
        self.lease: Lease | None = None
        directory = Path(config.state_directory)
        try:
            # Avoid multiple path aliases and network/junction-backed state.
            for path in [directory, *directory.parents]:
                if path.is_symlink() or path.is_junction():
                    raise OutlookError("state_path_alias_rejected")
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if os.name != "nt":
                directory.chmod(0o700)
            db_path = directory / "runtime.sqlite3"
            for path in [
                db_path,
                directory / "runtime.lock",
                directory / "runtime.sqlite3-wal",
                directory / "runtime.sqlite3-shm",
            ]:
                if path.is_symlink() or (path.exists() and path.stat().st_nlink != 1):
                    raise OutlookError("state_path_alias_rejected")
            self._lock = ProcessLock(directory / "runtime.lock")
            fd = os.open(db_path, os.O_RDWR | os.O_CREAT, 0o600)
            os.close(fd)
            self._connection = sqlite3.connect(db_path, isolation_level=None, timeout=5)
            self.db.row_factory = sqlite3.Row
            if self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0].casefold() != "wal":
                raise OutlookError("wal_unavailable")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA busy_timeout=5000")
            self._migrate_and_bind()
            with self.transaction() as db:
                row = db.execute("SELECT generation FROM lease WHERE id=1").fetchone()
                generation = int(row[0]) + 1 if row else 1
                self.lease = Lease(uuid4().hex, generation)
                db.execute(
                    "INSERT OR REPLACE INTO lease VALUES (1,?,?,?)",
                    (self.lease.owner, generation, self.clock().timestamp() + config.lease_seconds),
                )
        except (OSError, sqlite3.Error):
            self.close()
            raise OutlookError("state_initialization_failed") from None
        except BaseException:
            self.close()
            raise

    @property
    def db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise OutlookError("state_closed")
        return self._connection

    @contextmanager
    def transaction(self, *, lease: Lease | None = None) -> Iterator[sqlite3.Connection]:
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if lease is not None:
                row = self.db.execute(
                    "SELECT owner,generation,expires FROM lease WHERE id=1"
                ).fetchone()
                if (
                    row is None
                    or row[0] != lease.owner
                    or row[1] != lease.generation
                    or row[2] <= self.clock().timestamp()
                ):
                    raise OutlookError("lease_lost")
            yield self.db
            self.db.execute("COMMIT")
        except BaseException as error:
            if self._connection is not None and self.db.in_transaction:
                try:
                    self.db.execute("ROLLBACK")
                except sqlite3.Error:
                    raise OutlookError("state_transaction_failed") from None
            if isinstance(error, sqlite3.Error):
                raise OutlookError("state_transaction_failed") from None
            raise

    def _migrate_and_bind(self) -> None:
        with self.transaction() as db:
            version = int(db.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, 1}:
                raise OutlookError("unsupported_state_schema")
            if version == 0:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                    raise OutlookError("unrecognized_state_schema")
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute("PRAGMA user_version=1")
                values = {
                    "schema_digest": SCHEMA_DIGEST,
                    "scope": self.config.scope.model_dump_json(),
                    "activation_utc": self.clock().isoformat(),
                }
                db.executemany("INSERT INTO metadata VALUES (?,?)", values.items())
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            if (
                metadata.get("schema_digest") != SCHEMA_DIGEST
                or metadata.get("scope") != self.config.scope.model_dump_json()
            ):
                raise OutlookError("state_scope_or_schema_mismatch")
            actual = [
                r[0]
                for r in db.execute(
                    "SELECT sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid"
                )
            ]
            if actual != list(SCHEMA):
                raise OutlookError("state_schema_modified")

    def heartbeat(self) -> None:
        with self.transaction(lease=self.lease) as db:
            db.execute(
                "UPDATE lease SET expires=? WHERE id=1",
                (self.clock().timestamp() + self.config.lease_seconds,),
            )

    def observe(self, observations: Sequence[Observation]) -> int:
        if len(observations) > 1000:
            raise OutlookError("observation_batch_too_large")
        accepted = 0
        with self.transaction(lease=self.lease) as db:
            for item in observations:
                now = self.clock()
                if item.scope != self.config.scope:
                    raise OutlookError("observation_scope_mismatch")
                if (
                    item.observed_at > now + timedelta(minutes=5)
                    or item.observed_at + timedelta(days=7) <= now
                ):
                    raise OutlookError("observation_outside_validity")
                raw = item.model_dump(mode="json")
                raw.pop("observed_at")
                digest = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
                previous = db.execute(
                    "SELECT id,input_hash FROM observations WHERE message_id=? AND source_version=?",
                    (item.message_id, item.source_version),
                ).fetchone()
                if previous:
                    if previous[1] != digest:
                        raise OutlookError("observation_version_conflict")
                    continue
                current = db.execute(
                    "SELECT o.payload FROM messages m JOIN observations o ON o.id=m.current_observation WHERE m.message_id=?",
                    (item.message_id,),
                ).fetchone()
                if (
                    current
                    and Observation.model_validate_json(current[0]).observed_at > item.observed_at
                ):
                    raise OutlookError("stale_observation")
                cursor = db.execute(
                    "INSERT INTO observations(message_id,source_version,input_hash,payload,expires) VALUES (?,?,?,?,?)",
                    (
                        item.message_id,
                        item.source_version,
                        digest,
                        item.model_dump_json(),
                        (item.observed_at + timedelta(days=7)).timestamp(),
                    ),
                )
                observation_id = cursor.lastrowid
                db.execute(
                    "UPDATE work SET status='superseded' WHERE observation_id IN (SELECT id FROM observations WHERE message_id=?) AND status IN ('pending','retry')",
                    (item.message_id,),
                )
                db.execute(
                    "INSERT INTO messages(message_id,current_observation) VALUES (?,?) ON CONFLICT(message_id) DO UPDATE SET current_observation=excluded.current_observation",
                    (item.message_id, observation_id),
                )
                db.execute(
                    "UPDATE outbox SET status='superseded' WHERE decision_id IN (SELECT id FROM decisions WHERE message_id=?) AND status IN ('preview','pending','failed')",
                    (item.message_id,),
                )
                db.execute(
                    "INSERT INTO work(observation_id,status) VALUES (?,'pending')",
                    (observation_id,),
                )
                accepted += 1
        return accepted

    def pending(self, limit: int) -> list[tuple[int, Observation]]:
        if type(limit) is not int or not 1 <= limit <= self.config.batch_size:
            raise OutlookError("invalid_work_batch_size")
        with self.transaction(lease=self.lease) as db:
            rows = db.execute(
                "SELECT o.id,o.payload FROM observations o JOIN work w ON w.observation_id=o.id WHERE w.status IN ('pending','retry') AND w.next_attempt<=? ORDER BY o.id LIMIT ?",
                (self.clock().timestamp(), limit),
            ).fetchall()
            return [(int(row[0]), Observation.model_validate_json(row[1])) for row in rows]

    def record_decision(self, observation_id: int, decision: Decision) -> int:
        require_annotation_eligible(decision, self.config.scope, self.clock())
        with self.transaction(lease=self.lease) as db:
            row = db.execute(
                "SELECT o.message_id,o.source_version,o.expires,m.current_observation,m.decision_version,w.status FROM observations o JOIN messages m ON m.message_id=o.message_id JOIN work w ON w.observation_id=o.id WHERE o.id=?",
                (observation_id,),
            ).fetchone()
            if (
                row is None
                or row[0] != decision.message_id
                or row[1] != decision.source_version
                or row[3] != observation_id
                or row[5] not in {"pending", "retry"}
            ):
                raise OutlookError("stale_or_mismatched_decision")
            if row[2] <= self.clock().timestamp():
                raise OutlookError("observation_expired")
            observation = Observation.model_validate_json(
                db.execute(
                    "SELECT payload FROM observations WHERE id=?", (observation_id,)
                ).fetchone()[0]
            )
            if decision.expires_at > observation.observed_at + timedelta(days=30):
                raise OutlookError("decision_retention_exceeds_baseline")
            version = int(row[4]) + 1
            db.execute(
                "UPDATE outbox SET status='superseded' WHERE decision_id IN (SELECT id FROM decisions WHERE message_id=?) AND status IN ('preview','pending','failed')",
                (decision.message_id,),
            )
            cursor = db.execute(
                "INSERT INTO decisions(message_id,version,observation_id,payload,created,expires) VALUES (?,?,?,?,?,?)",
                (
                    decision.message_id,
                    version,
                    observation_id,
                    decision.model_dump_json(),
                    decision.decided_at.timestamp(),
                    decision.expires_at.timestamp(),
                ),
            )
            db.execute(
                "INSERT INTO outbox VALUES (?,'preview',?)", (cursor.lastrowid, decision.category)
            )
            db.execute(
                "UPDATE messages SET decision_version=? WHERE message_id=?",
                (version, decision.message_id),
            )
            db.execute(
                "UPDATE work SET status='completed',error_code=NULL WHERE observation_id=?",
                (observation_id,),
            )
            return version

    def fail_work(self, observation_id: int, code: str) -> None:
        # Callers supply internal codes, never exception text or email fields.
        if code not in {"observation_expired", "processing_failed"}:
            raise OutlookError("unsafe_work_error_code")
        with self.transaction(lease=self.lease) as db:
            row = db.execute(
                "SELECT attempts,status FROM work WHERE observation_id=?", (observation_id,)
            ).fetchone()
            if row is None or row[1] not in {"pending", "retry"}:
                raise OutlookError("work_not_pending")
            attempts = int(row[0]) + 1
            state = (
                "dead_letter"
                if attempts >= self.config.max_attempts or code == "observation_expired"
                else "retry"
            )
            db.execute(
                "UPDATE work SET status=?,attempts=?,next_attempt=?,error_code=? WHERE observation_id=?",
                (
                    state,
                    attempts,
                    self.clock().timestamp() + min(300, 2**attempts),
                    code,
                    observation_id,
                ),
            )

    def summary(self) -> dict[str, int | str]:
        with self.transaction(lease=self.lease) as db:
            result: dict[str, int | str] = {
                "schema_version": 1,
                "journal_mode": "wal",
                "runtime_stage": "foundation_only",
            }
            for table in ("observations", "decisions", "outbox"):
                result[table] = int(db.execute("SELECT count(*) FROM " + table).fetchone()[0])
            for status in ("pending", "retry", "completed", "dead_letter"):
                result["work_" + status] = int(
                    db.execute("SELECT count(*) FROM work WHERE status=?", (status,)).fetchone()[0]
                )
            for status in ("preview", "pending", "superseded", "failed"):
                result["outbox_" + status] = int(
                    db.execute("SELECT count(*) FROM outbox WHERE status=?", (status,)).fetchone()[
                        0
                    ]
                )
            result["activation_utc"] = str(
                db.execute("SELECT value FROM metadata WHERE key='activation_utc'").fetchone()[0]
            )
            return result

    def close(self) -> None:
        if self._connection is not None:
            try:
                if self.lease is not None:
                    self.db.execute(
                        "UPDATE lease SET expires=0 WHERE id=1 AND owner=? AND generation=?",
                        (self.lease.owner, self.lease.generation),
                    )
            except sqlite3.Error:
                pass
            finally:
                try:
                    self._connection.close()
                except sqlite3.Error:
                    pass
            self._connection = None
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
