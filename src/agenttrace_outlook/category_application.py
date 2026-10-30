"""Bounded monitor wiring for the existing scoped, journaled category writer."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agenttrace_feasibility.validation import canonical_bytes, load_json

from .category_contracts import CategorySettings
from .category_write_contracts import CategoryEndpointQualification
from .category_writer import CategoryWriter
from .config import RuntimeConfig
from .errors import OutlookError


@dataclass(frozen=True)
class ApplicationSettings:
    settings: CategorySettings
    qualification: CategoryEndpointQualification

    @classmethod
    def read(
        cls, runtime: RuntimeConfig, settings_path: Path, qualification_path: Path
    ) -> "ApplicationSettings":
        settings = CategorySettings.model_validate_json(canonical_bytes(load_json(settings_path)))
        qualification = CategoryEndpointQualification.model_validate_json(
            canonical_bytes(load_json(qualification_path))
        )
        if (
            runtime.scope != settings.scope
            or not runtime.sync_enabled
            or runtime.reader_identity is None
            or runtime.reader_identity.client_id == settings.writer_identity.client_id
            or (
                runtime.sender_source
                and runtime.sender_source.audit_identity.client_id
                == settings.writer_identity.client_id
            )
        ):
            raise OutlookError("separate_scoped_category_writer_required")
        qualification.require_current(settings, datetime.now(UTC))
        return cls(settings, qualification)


class CategoryApplication:
    """Resume due receipts before newer decisions; never reset blocked attempts automatically."""

    def __init__(self, writer: CategoryWriter):
        self.writer = writer

    def run_cycle(self) -> list[dict[str, object]]:
        store = self.writer.store
        store.heartbeat()
        self.writer.plan()
        with store.transaction(lease=store.lease) as db:
            rows = db.execute(
                "SELECT id FROM category_intents WHERE status IN "
                "('pending','prepared','uncertain','rollback_pending') AND due<=? "
                "ORDER BY CASE WHEN status IN ('prepared','uncertain','rollback_pending') "
                "THEN 0 ELSE 1 END,due,id LIMIT ?",
                (store.clock().timestamp(), min(store.config.batch_size, 10)),
            ).fetchall()
        return [self.writer.step(row[0]) for row in rows]

    def summary(self) -> dict[str, int | str]:
        store = self.writer.store
        with store.transaction(lease=store.lease) as db:
            counts = dict(
                db.execute(
                    "SELECT i.status,count(*) FROM category_intents i JOIN decisions d "
                    "ON d.id=i.decision_id JOIN messages m ON m.message_id=d.message_id "
                    "WHERE (d.version=m.decision_version AND EXISTS(SELECT 1 FROM sync_items s "
                    "WHERE s.message_id=d.message_id AND s.status='eligible')) OR i.status IN "
                    "('prepared','uncertain','rollback_pending','rollback_blocked') "
                    "GROUP BY i.status"
                ).fetchall()
            )
        pending = sum(
            counts.get(s, 0) for s in ("pending", "prepared", "uncertain", "rollback_pending")
        )
        blocked = sum(counts.get(s, 0) for s in ("blocked", "rollback_blocked"))
        return {
            "category_pending": pending,
            "category_blocked": blocked,
            "category_confirmed": sum(counts.get(s, 0) for s in ("applied", "unchanged")),
            "category_reconciled": counts.get("reconciled", 0),
            "category_health": "degraded" if blocked else "pending" if pending else "current",
        }
