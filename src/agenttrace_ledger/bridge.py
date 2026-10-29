"""Bind a committed ingestion version to an already-authorized transient snapshot."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal
from uuid import UUID

from agenttrace_text_normalization import BodyExtractor

from agenttrace_ingestion.contracts import Enrollment, MessageSnapshot
from agenttrace_ingestion.store import IngestionStore

from .canonical import LedgerError, text
from .contracts import MessageObservation, Region
from .store import EvidenceLedger, utc_now


def enroll_ingestion_source(
    ledger: EvidenceLedger, ingestion: IngestionStore, enrollment: Enrollment
) -> None:
    """Operator action; inspect the authenticated source binding, not a caller label."""
    with ingestion.database.connect() as c:
        row = c.execute(
            "SELECT scope_cipher,source_kind FROM ingest_sources WHERE source_ref=%s",
            (enrollment.source_ref,),
        ).fetchone()
    if not row or row["source_kind"] != "mailbox":
        raise LedgerError("mailbox_ingestion_source_required")
    scope = ingestion.cipher.open(
        bytes(row["scope_cipher"]), context="scope:" + str(enrollment.source_ref)
    )
    if scope["tenant_id"] != str(enrollment.tenant_id) or scope["mailbox_id"] != str(
        enrollment.mailbox_id
    ):
        raise LedgerError("ingestion_scope_mismatch")
    ledger.enroll_scope(
        enrollment.tenant_id,
        enrollment.mailbox_id,
        roles=("agenttrace_ledger", "agenttrace_collector"),
    )
    ledger.enroll_observer(
        enrollment.tenant_id,
        enrollment.mailbox_id,
        enrollment.source_ref,
        schema_version="ingestion-v1",
        capture_basis="committed_ingestion",
    )


def observe_ingested_snapshot(
    ledger: EvidenceLedger,
    ingestion: IngestionStore,
    enrollment: Enrollment,
    snapshot: MessageSnapshot,
) -> UUID:
    """No body lookup, Graph call or permission expansion; the caller owns its read authorization."""
    message_ref = ingestion.cipher.reference(str(enrollment.source_ref), snapshot.immutable_id)
    version_ref = ingestion.cipher.reference(str(message_ref), snapshot.change_key)
    with ingestion.database.connect() as c:
        row = c.execute(
            "SELECT v.*,m.current_version,m.visibility,m.copy_role,m.locator_cipher FROM ingest_versions v JOIN ingest_copies m ON m.message_ref=v.message_ref AND m.source_ref=v.source_ref WHERE v.version_ref=%s AND v.source_ref=%s AND v.message_ref=%s AND v.expires_at>now()",
            (version_ref, enrollment.source_ref, message_ref),
        ).fetchone()
    if (
        not row
        or row["obsolete"]
        or row["current_version"] != version_ref
        or row["visibility"] != "current"
    ):
        raise LedgerError("committed_current_ingestion_version_required")
    if snapshot.parent_folder_id not in enrollment.folder_ids or not snapshot.subject.startswith(
        enrollment.synthetic_subject_prefix
    ):
        raise LedgerError("snapshot_outside_authorized_ingestion_scope")
    if not row["received_at"] > utc_now() - timedelta(days=7):
        raise LedgerError("ingestion_raw_link_expired")
    locator = ingestion.cipher.open(
        bytes(row["locator_cipher"]), context="message:" + str(message_ref)
    )
    if (
        locator["immutable_id"] != snapshot.immutable_id
        or locator.get("internet_message_id") != snapshot.internet_message_id
    ):
        raise LedgerError("snapshot_identifier_mapping_mismatch")
    if (snapshot.body is None) != (row["content_digest"] is None) or (
        snapshot.body is not None
        and ingestion.cipher.digest(snapshot.body.encode()) != row["content_digest"]
    ):
        raise LedgerError("snapshot_does_not_match_committed_content_version")
    extractor = BodyExtractor()
    extraction = (
        extractor.extract(snapshot.body, snapshot.body_type, attachments=snapshot.attachment_count)
        if snapshot.body is not None
        else extractor.unavailable(snapshot.unavailable_reason or "body_unavailable")
    )
    if any(row["summary"].get(k) != v for k, v in extraction.summary().items()):
        raise LedgerError("ingestion_extraction_contract_mismatch")
    usable_content = snapshot.body is not None and extraction.status == "extracted"
    if usable_content and text(extraction.normalized_text) != extraction.normalized_text:
        raise LedgerError("canonical_source_offset_mapping_required")
    # No supplied role can upgrade an unknown ingestion observation into a sender.
    role = row["copy_role"]
    state: Literal["draft", "sent", "received", "unknown"] = (
        "draft"
        if snapshot.is_draft
        else "sent"
        if role == "sender"
        else "received"
        if role == "recipient"
        else "unknown"
    )
    message = MessageObservation(
        tenant_id=enrollment.tenant_id,
        mailbox_id=enrollment.mailbox_id,
        source_ref=enrollment.source_ref,
        source_event_ref=version_ref,
        source_schema_version="ingestion-v1",
        namespace="graph_immutable",
        immutable_id=snapshot.immutable_id,
        internet_message_id=snapshot.internet_message_id,
        version_ref=version_ref,
        copy_role=role,
        state=state,
        observed_at=row["received_at"],
        source_event_at=snapshot.modified_at,
        sent_at=snapshot.source_event_at,
        subject=snapshot.subject,
        body=extraction.normalized_text if usable_content else "",
        content_available=usable_content,
        recipients=(),
        recipients_complete=False,
        regions=tuple(
            Region(
                start=r.start, end=r.end, role="authored" if r.kind == "authored" else "inherited"
            )
            for r in extraction.regions
            if usable_content and r.end > r.start
        ),
        normalization_version=extraction.version,
    )
    return ledger.observe(message)
