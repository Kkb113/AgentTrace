"""Atomic sync checkpoints and operational accounting; opaque cursors never enter logs."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .errors import OutlookError, SourceError
from .state import StateStore


class SyncState:
    def __init__(self, store: StateStore):
        self.store = store
        with store.transaction(lease=store.lease) as db:
            configured = store.config.backfill_since
            activation = datetime.fromisoformat(
                db.execute("SELECT value FROM metadata WHERE key='activation_utc'").fetchone()[0]
            )
            cutoff = configured or activation
            boundary = configured.isoformat() if configured else "activation"
            previous = db.execute("SELECT value FROM metadata WHERE key='sync_boundary'").fetchone()
            if previous and previous[0] != boundary:
                raise OutlookError("sync_boundary_changed")
            if not previous:
                if (
                    configured
                    and not store.clock() - timedelta(days=7) <= configured <= store.clock()
                ):
                    raise OutlookError("backfill_outside_seven_day_window")
                db.executemany(
                    "INSERT INTO metadata VALUES (?,?)",
                    (
                        ("sync_boundary", boundary),
                        ("sync_cutoff", cutoff.isoformat()),
                        ("discovery_epoch", "0"),
                    ),
                )
                for name in ("drafts", "sentitems", "outbox", "deleteditems"):
                    self.enqueue(db, "system", name)
            self.cutoff = cutoff

    @staticmethod
    def tick(db: sqlite3.Connection) -> int:
        if db.execute("SELECT 1 FROM metadata WHERE key='sync_schedule'").fetchone() is None:
            seed = int(db.execute("SELECT coalesce(max(visited),0) FROM sync_jobs").fetchone()[0])
            db.execute("INSERT INTO metadata VALUES ('sync_schedule',?)", (str(seed),))
        return int(
            db.execute(
                "UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='sync_schedule' RETURNING value"
            ).fetchone()[0]
        )

    def enqueue(self, db: sqlite3.Connection, kind: str, target: str, epoch: int = 1) -> None:
        key = kind + ":" + target
        db.execute(
            "INSERT INTO sync_jobs(key,kind,target,epoch,visited) VALUES (?,?,?,?,?) ON CONFLICT(key) DO NOTHING",
            (key, kind, target, epoch, self.tick(db)),
        )

    def hydrate(self, db: sqlite3.Connection, message_id: str) -> None:
        self.enqueue(db, "detail", message_id)
        db.execute(
            "UPDATE sync_jobs SET generation=generation+1,status=CASE WHEN status IN ('blocked','dead_letter') THEN status ELSE 'due' END,due=CASE WHEN attempts>0 THEN due ELSE 0 END WHERE key=?",
            ("detail:" + message_id,),
        )
        now = self.store.clock().timestamp()
        db.execute(
            "INSERT INTO sync_items(message_id,status,first_seen,expires) VALUES (?,'pending',?,?) ON CONFLICT(message_id) DO UPDATE SET status=CASE WHEN status='eligible' THEN status ELSE 'pending' END",
            (message_id, now, now + 7 * 86400),
        )

    def gap(self, db: sqlite3.Connection, key: str, code: str) -> None:
        db.execute(
            "INSERT INTO sync_gaps(job_key,code,created) SELECT ?,?,? WHERE NOT EXISTS (SELECT 1 FROM sync_gaps WHERE job_key=? AND code=? AND resolved=0)",
            (key, code, self.store.clock().timestamp(), key, code),
        )

    def start_discovery(self) -> None:
        store = self.store
        with store.transaction(lease=store.lease) as db:
            if db.execute(
                "SELECT 1 FROM sync_jobs WHERE kind='system' AND status!='idle'"
            ).fetchone():
                return
            root = db.execute(
                "SELECT status,due FROM sync_jobs WHERE key='discover:root'"
            ).fetchone()
            if root and (root[0] != "idle" or root[1] > store.clock().timestamp()):
                return
            if (
                root
                and db.execute(
                    "SELECT 1 FROM sync_jobs WHERE kind='discover' AND status NOT IN ('idle','excluded')"
                ).fetchone()
            ):
                return
            epoch = (
                int(
                    db.execute("SELECT value FROM metadata WHERE key='discovery_epoch'").fetchone()[
                        0
                    ]
                )
                + 1
            )
            db.execute("UPDATE metadata SET value=? WHERE key='discovery_epoch'", (str(epoch),))
            self.enqueue(db, "discover", "root", epoch)
            db.execute(
                "UPDATE sync_jobs SET cursor=NULL,status='due',due=0,epoch=?,generation=generation+1 WHERE key='discover:root'",
                (epoch,),
            )

    def next_job(self) -> dict[str, Any] | None:
        with self.store.transaction(lease=self.store.lease) as db:
            row = db.execute(
                "SELECT * FROM sync_jobs WHERE status='due' AND due<=? ORDER BY visited,rowid LIMIT 1",
                (self.store.clock().timestamp(),),
            ).fetchone()
            return dict(row) if row else None

    def checkpoint(
        self, db: sqlite3.Connection, job: dict[str, Any], *, cursor: str | None, complete: bool
    ) -> None:
        now = self.store.clock().timestamp()
        status = "due" if job["kind"] == "delta" or not complete else "idle"
        due = (
            now
            + (
                self.store.config.sync_poll_seconds
                if job["kind"] == "delta"
                else self.store.config.folder_refresh_seconds
            )
            if complete
            else 0
        )
        changed = db.execute(
            "UPDATE sync_jobs SET cursor=?,generation=generation+1,status=?,due=?,attempts=0,error=NULL,visited=? WHERE key=? AND generation=?",
            (cursor, status, due, self.tick(db), job["key"], job["generation"]),
        ).rowcount
        if changed != 1:
            raise OutlookError("stale_sync_page")
        db.execute(
            "UPDATE sync_gaps SET resolved=1 WHERE job_key=? AND code NOT IN ('cursor_expired_unobserved_window','discovery_cursor_restarted','message_removed_or_unreadable','folder_removed_during_inventory')",
            (job["key"],),
        )

    def check_generation(self, db: sqlite3.Connection, job: dict[str, Any]) -> None:
        current = db.execute(
            "SELECT generation FROM sync_jobs WHERE key=?", (job["key"],)
        ).fetchone()
        if current is None or current[0] != job["generation"]:
            raise OutlookError("stale_sync_page")

    def finish_discovery(self, db: sqlite3.Connection, epoch: int) -> None:
        if db.execute(
            "SELECT 1 FROM sync_jobs WHERE kind='discover' AND epoch=? AND status NOT IN ('idle','excluded')",
            (epoch,),
        ).fetchone():
            return
        missing = list(
            db.execute("SELECT id FROM folders WHERE seen_epoch<? AND active=1", (epoch,))
        )
        for row in missing:
            self.remove_folder(db, row[0])

    def remove_folder(self, db: sqlite3.Connection, folder_id: str) -> None:
        db.execute("UPDATE folders SET active=0 WHERE id=?", (folder_id,))
        db.execute(
            "UPDATE sync_jobs SET status='excluded',generation=generation+1 WHERE kind='delta' AND target=?",
            (folder_id,),
        )
        for row in db.execute(
            "SELECT message_id FROM memberships WHERE folder_id=? AND present=1", (folder_id,)
        ).fetchall():
            self.hydrate(db, row[0])
        db.execute("UPDATE memberships SET present=0 WHERE folder_id=?", (folder_id,))

    def invalidate(self, db: sqlite3.Connection, message_id: str, status: str) -> None:
        db.execute("UPDATE sync_items SET status=? WHERE message_id=?", (status, message_id))
        db.execute("DELETE FROM snapshots WHERE message_id=?", (message_id,))
        db.execute(
            "UPDATE work SET status='superseded' WHERE observation_id IN (SELECT id FROM observations WHERE message_id=?) AND status IN ('pending','retry')",
            (message_id,),
        )
        db.execute(
            "UPDATE outbox SET status='superseded' WHERE decision_id IN (SELECT id FROM decisions WHERE message_id=?) AND status IN ('pending','preview','failed')",
            (message_id,),
        )

    def fail(self, job: dict[str, Any], error: SourceError, jitter: float) -> None:
        store = self.store
        with store.transaction(lease=store.lease) as db:
            self.check_generation(db, job)
            if (
                error.code == "source_cursor_expired"
                and job["cursor"]
                and job["kind"] in {"delta", "discover"}
            ):
                if job["kind"] == "discover":
                    self.gap(db, job["key"], "discovery_cursor_restarted")
                    db.execute(
                        "UPDATE sync_jobs SET cursor=NULL,generation=generation+1,due=0,visited=?,attempts=0,error='cursor_resynchronizing' WHERE key=?",
                        (self.tick(db), job["key"]),
                    )
                    return
                self.gap(db, job["key"], "cursor_expired_unobserved_window")
                db.execute(
                    "UPDATE sync_jobs SET cursor=NULL,epoch=epoch+1,generation=generation+1,due=0,visited=?,attempts=0,error='cursor_resynchronizing' WHERE key=?",
                    (self.tick(db), job["key"]),
                )
                return
            if (
                error.code == "source_item_not_found"
                and job["kind"] == "discover"
                and job["target"] != "root"
            ):
                self.remove_folder(db, job["target"])
                self.gap(db, job["key"], "folder_removed_during_inventory")
                db.execute(
                    "UPDATE sync_jobs SET status='excluded',generation=generation+1 WHERE key=?",
                    (job["key"],),
                )
                self.finish_discovery(db, job["epoch"])
                return
            attempts = int(job["attempts"]) + 1
            status = (
                "due"
                if error.retryable and attempts < store.config.max_attempts
                else "dead_letter"
                if error.retryable
                else "blocked"
            )
            code = error.code
            if error.retry_after >= 3600:
                status, code = "blocked", "retry_after_requires_operator"
            delay = max(error.retry_after, min(300, 2 ** min(attempts, 10))) + jitter
            db.execute(
                "UPDATE sync_jobs SET status=?,attempts=?,error=?,due=?,visited=? WHERE key=?",
                (
                    status,
                    attempts,
                    code,
                    store.clock().timestamp() + delay,
                    self.tick(db),
                    job["key"],
                ),
            )
            if status != "due":
                self.gap(db, job["key"], code)

    def retry_failed(self) -> int:
        with self.store.transaction(lease=self.store.lease) as db:
            count = db.execute(
                "UPDATE sync_jobs SET status='due',due=0,attempts=0,error=NULL,generation=generation+1 WHERE status IN ('blocked','dead_letter')"
            ).rowcount
            # Retry itself proves nothing; a successful checkpoint can close a
            # recoverable outage. Unobserved windows and historical rows remain.
            return count

    def summary(self) -> dict[str, int | str]:
        with self.store.transaction(lease=self.store.lease) as db:
            result: dict[str, int | str] = {"sync_cutoff_utc": self.cutoff.isoformat()}
            for name, query in {
                "folders_receiving": "SELECT count(*) FROM folders WHERE active=1 AND excluded IS NULL",
                "folders_excluded": "SELECT count(*) FROM folders WHERE active=1 AND excluded IS NOT NULL",
                "sync_jobs_due": "SELECT count(*) FROM sync_jobs WHERE status='due'",
                "sync_jobs_blocked": "SELECT count(*) FROM sync_jobs WHERE status='blocked'",
                "sync_jobs_dead_letter": "SELECT count(*) FROM sync_jobs WHERE status='dead_letter'",
                "sync_gaps": "SELECT count(*) FROM sync_gaps WHERE resolved=0",
                "sync_items": "SELECT count(*) FROM sync_items",
                "sync_pending_items": "SELECT count(*) FROM sync_items WHERE status='pending'",
                "sync_eligible_items": "SELECT count(*) FROM sync_items WHERE status='eligible'",
                "oldest_pending_epoch_seconds": "SELECT coalesce(min(first_seen),0) FROM sync_items WHERE status='pending'",
                "discovery_jobs_pending": "SELECT count(*) FROM sync_jobs WHERE kind='discover' AND status NOT IN ('idle','excluded')",
                "sync_retry_waiting": "SELECT count(*) FROM sync_jobs WHERE status='due' AND attempts>0",
            }.items():
                result[name] = int(db.execute(query).fetchone()[0])
            oldest = int(result.pop("oldest_pending_epoch_seconds"))
            result["sync_ready_jobs"] = int(
                db.execute(
                    "SELECT count(*) FROM sync_jobs WHERE status='due' AND due<=?",
                    (self.store.clock().timestamp(),),
                ).fetchone()[0]
            )
            result["oldest_pending_age_seconds"] = (
                max(0, int(self.store.clock().timestamp()) - oldest) if oldest else 0
            )
            result["sync_health"] = (
                "degraded"
                if result["sync_gaps"]
                else "collecting"
                if result["sync_pending_items"]
                or result["discovery_jobs_pending"]
                or result["sync_ready_jobs"]
                else "current"
            )
            return result

    def system_ids(self, db: sqlite3.Connection) -> set[str]:
        row = db.execute("SELECT value FROM metadata WHERE key='system_folder_ids'").fetchone()
        return set(json.loads(row[0])) if row else set()
