"""Fair, bounded GET-only synchronization; every page commits with its durable work."""

from __future__ import annotations

import hashlib
import json
import random
from datetime import UTC, datetime
from typing import Any

from .contracts import Observation
from .errors import OutlookError, SourceError
from .mail_semantics import sender_snapshot
from .reader import MailReader
from .state import StateStore
from .sync_state import SyncState


def opaque(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 2048
        or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:/+=-"
            for c in value
        )
    ):
        raise SourceError("invalid_source_identifier")
    return value


def source_time(value: object) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(UTC)
    except (ValueError, OverflowError):
        raise SourceError("source_timestamp_invalid") from None


class Synchronizer:
    def __init__(self, store: StateStore, reader: MailReader):
        self.store, self.reader = store, reader
        self.state = SyncState(store)

    def run_cycle(self) -> int:
        self.state.start_discovery()
        completed = 0
        for _ in range(self.store.config.sync_operations_per_cycle):
            self.store.heartbeat()
            self.state.start_discovery()
            job = self.state.next_job()
            if job is None:
                break
            try:
                if job["kind"] == "system":
                    self.system(job)
                elif job["kind"] == "detail":
                    self.detail(job)
                else:
                    self.page(job)
            except SourceError as error:
                self.state.fail(job, error, random.SystemRandom().uniform(0, 1))
            completed += 1
        return completed

    def system(self, job: dict[str, Any]) -> None:
        identity = opaque(self.reader.well_known(job["target"]).get("id"))
        with self.store.transaction(lease=self.store.lease) as db:
            self.state.check_generation(db, job)
            ids = self.state.system_ids(db) | {identity}
            db.execute(
                "INSERT INTO metadata VALUES ('system_folder_ids',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(sorted(ids)),),
            )
            self.state.checkpoint(db, job, cursor=None, complete=True)

    def page(self, job: dict[str, Any]) -> None:
        page = self.reader.page(job["kind"], job["target"], job["cursor"])
        values = page.get("value")
        if (
            not isinstance(values, list)
            or len(values) > 1000
            or not all(isinstance(v, dict) for v in values)
        ):
            raise SourceError("source_page_invalid")
        next_link, delta_link = page.get("@odata.nextLink"), page.get("@odata.deltaLink")
        if next_link is not None and delta_link is not None:
            raise SourceError("source_page_invalid")
        complete = next_link is None
        continuation = next_link or delta_link
        if job["kind"] == "delta" and not continuation:
            raise SourceError("source_checkpoint_missing")
        if continuation is not None:
            self.reader.validate_cursor(continuation, job["kind"], job["target"])
        if next_link and next_link == (
            job["cursor"] or self.reader.collection_url(job["kind"], job["target"])
        ):
            raise SourceError("source_cursor_loop")
        with self.store.transaction(lease=self.store.lease) as db:
            self.state.check_generation(db, job)
            for value in values:
                identity = opaque(value.get("id"))
                if job["kind"] == "discover":
                    if "@removed" in value:
                        self.state.remove_folder(db, identity)
                        continue
                    parent = opaque(value.get("parentFolderId"))
                    hidden, children = value.get("isHidden"), value.get("childFolderCount")
                    if type(hidden) is not bool or type(children) is not int or children < 0:
                        raise SourceError("source_folder_invalid")
                    previous = db.execute(
                        "SELECT excluded FROM folders WHERE id=?", (job["target"],)
                    ).fetchone()
                    excluded = (
                        "system_folder"
                        if identity in self.state.system_ids(db)
                        else "hidden_folder"
                        if hidden
                        else previous[0]
                        if previous
                        else None
                    )
                    db.execute(
                        "INSERT INTO folders VALUES (?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,excluded=excluded.excluded,seen_epoch=excluded.seen_epoch,active=1",
                        (identity, parent, excluded, job["epoch"]),
                    )
                    if children:
                        self.state.enqueue(db, "discover", identity, job["epoch"])
                        db.execute(
                            "UPDATE sync_jobs SET cursor=NULL,epoch=?,status='due',due=0,generation=generation+1 WHERE key=? AND epoch<?",
                            (job["epoch"], "discover:" + identity, job["epoch"]),
                        )
                    if excluded is None:
                        self.state.enqueue(db, "delta", identity)
                        db.execute(
                            "UPDATE sync_jobs SET status='due',cursor=NULL,due=0,epoch=epoch+1,generation=generation+1 WHERE key=? AND status='excluded'",
                            ("delta:" + identity,),
                        )
                    else:
                        db.execute(
                            "UPDATE sync_jobs SET status='excluded',generation=generation+1 WHERE key=?",
                            ("delta:" + identity,),
                        )
                        # Newly excluded coverage must re-resolve any retained
                        # copies, rather than leaving their previews eligible.
                        for row in db.execute(
                            "SELECT message_id FROM sync_items WHERE folder_id=? AND status='eligible'",
                            (identity,),
                        ).fetchall():
                            self.state.hydrate(db, row[0])
                else:
                    # Folder tombstones are not global deletions. Resolve using a
                    # mailbox-wide immutable-ID GET before changing message state.
                    db.execute(
                        "INSERT INTO memberships VALUES (?,?,?,?) ON CONFLICT(folder_id,message_id) DO UPDATE SET present=excluded.present,epoch=excluded.epoch",
                        (job["target"], identity, int("@removed" not in value), job["epoch"]),
                    )
                    self.state.hydrate(db, identity)
            if complete and job["kind"] == "delta":
                for row in db.execute(
                    "SELECT message_id FROM memberships WHERE folder_id=? AND epoch<? AND present=1",
                    (job["target"], job["epoch"]),
                ).fetchall():
                    self.state.hydrate(db, row[0])
                db.execute(
                    "UPDATE memberships SET present=0 WHERE folder_id=? AND epoch<?",
                    (job["target"], job["epoch"]),
                )
            self.state.checkpoint(db, job, cursor=continuation, complete=complete)
            if job["kind"] == "discover" and complete:
                self.state.finish_discovery(db, job["epoch"])

    def detail(self, job: dict[str, Any]) -> None:
        try:
            detail = self.reader.sync_detail(job["target"], include_headers=False)
            # Do not request ordinary or historical headers merely to establish
            # that the item is outside the synthetic qualification population.
            if (
                detail.get("isDraft") is False
                and source_time(detail.get("receivedDateTime")) >= self.state.cutoff
                and isinstance(detail.get("subject"), str)
                and detail["subject"].startswith(self.store.config.synthetic_subject_prefix)
            ):
                detail = self.reader.sync_detail(job["target"], include_headers=True)
        except SourceError as error:
            if error.code != "source_item_not_found":
                raise
            with self.store.transaction(lease=self.store.lease) as db:
                self.state.check_generation(db, job)
                self.state.invalidate(db, job["target"], "gone_or_inaccessible")
                self.state.gap(db, job["key"], "message_removed_or_unreadable")
                self.state.checkpoint(db, job, cursor=None, complete=True)
            return
        identity, folder = opaque(detail.get("id")), opaque(detail.get("parentFolderId"))
        if identity != job["target"] or type(detail.get("isDraft")) is not bool:
            raise SourceError("source_message_mismatch")
        received, now = source_time(detail.get("receivedDateTime")), self.store.clock()
        if received > now:
            raise SourceError("source_timestamp_invalid")
        with self.store.transaction(lease=self.store.lease) as db:
            self.state.check_generation(db, job)
            location = db.execute(
                "SELECT excluded,active FROM folders WHERE id=?", (folder,)
            ).fetchone()
            if location is None:
                # A move may reach a folder before discovery. Keep the original
                # job/cursor and retry after inventory catches up.
                raise SourceError(
                    "message_folder_pending_discovery",
                    retryable=True,
                    retry_after=self.store.config.folder_refresh_seconds,
                )
            db.execute("UPDATE memberships SET present=0 WHERE message_id=?", (identity,))
            db.execute(
                "INSERT INTO memberships VALUES (?,?,1,0) ON CONFLICT(folder_id,message_id) DO UPDATE SET present=1",
                (folder, identity),
            )
            status = (
                "excluded"
                if location[0] or not location[1] or detail["isDraft"]
                else "history"
                if received < self.state.cutoff
                else "non_synthetic"
                if not str(detail.get("subject", "")).startswith(
                    self.store.config.synthetic_subject_prefix
                )
                else "eligible"
            )
            if status != "eligible":
                self.state.invalidate(db, identity, status)
            else:
                semantic, complete = sender_snapshot(detail)
                digest = hashlib.sha256(json.dumps(semantic, sort_keys=True).encode()).hexdigest()
                current = db.execute(
                    "SELECT semantic_hash,status,revision FROM sync_items WHERE message_id=?",
                    (identity,),
                ).fetchone()
                if current is None:
                    raise OutlookError("sync_item_missing")
                if current[0] != digest or current[1] != "eligible":
                    revision = int(current[2]) + 1
                    observation = Observation(
                        scope=self.store.config.scope,
                        message_id=identity,
                        source_version=digest + ":" + str(revision),
                        observed_at=now,
                        received_at=received,
                        inspection_complete=complete,
                        source_digest=digest,
                    )
                    self.store._observe(db, [observation])
                    db.execute(
                        "INSERT INTO snapshots VALUES (?,?,?) ON CONFLICT(message_id) DO UPDATE SET payload=excluded.payload,expires=excluded.expires",
                        (
                            identity,
                            json.dumps(semantic, sort_keys=True),
                            now.timestamp() + 7 * 86400,
                        ),
                    )
                    db.execute(
                        "UPDATE sync_items SET semantic_hash=?,revision=? WHERE message_id=?",
                        (digest, revision, identity),
                    )
                db.execute(
                    "UPDATE sync_items SET status='eligible' WHERE message_id=?", (identity,)
                )
            db.execute(
                "UPDATE sync_items SET folder_id=?,provider_version=? WHERE message_id=?",
                (folder, str(detail.get("changeKey", "")), identity),
            )
            self.state.checkpoint(db, job, cursor=None, complete=True)
