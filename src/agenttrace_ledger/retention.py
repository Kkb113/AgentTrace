"""Operator-only expiry maintenance and independently held, expiring history anchors."""

from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import sql

from .canonical import LedgerError, fingerprint
from .store import EvidenceLedger, utc_now


def purge_expired(ledger: EvidenceLedger) -> dict[str, int]:
    if ledger.database.settings.database_user != "agenttrace":
        raise LedgerError("ledger_retention_operator_required")
    counts = {}
    with ledger.database.connect() as c:
        for table in ["ledger_inputs", "ledger_conflicts", "ledger_receipts", "ledger_messages"]:
            # Message observations cannot outlive active receipts through this routine.
            extra = (
                " AND NOT EXISTS(SELECT 1 FROM ledger_receipts r WHERE r.scope_ref=ledger_messages.scope_ref AND r.message_ref=ledger_messages.message_ref AND r.version_ref=ledger_messages.version_ref)"
                if table == "ledger_messages"
                else ""
            )
            result = c.execute(
                sql.SQL("DELETE FROM {} WHERE expires_at<=now(){}").format(
                    sql.Identifier(table), sql.SQL(extra)
                )
            )
            counts[table] = result.rowcount
    return counts


def checkpoint(
    ledger: EvidenceLedger, tenant: UUID, mailbox: UUID, message: UUID
) -> dict[str, Any]:
    history = ledger.history(tenant, mailbox, message)
    if not history:
        raise LedgerError("history_anchor_requires_retained_inputs")
    entries = [
        {
            "input_ref": r["input_ref"],
            "prior_input_ref": r["prior_input_ref"],
            "view_digest": r["input_digest"],
        }
        for r in history
    ]
    value = {
        "schema_version": "1.0",
        "tenant_id": str(tenant),
        "mailbox_id": str(mailbox),
        "message_ref": str(message),
        "expires_at": min(r["expires_at"] for r in history),
        "entries": entries,
    }
    return {**value, "seal": fingerprint(ledger._key(tenant), tenant, "history-anchor", value)}


def verify_checkpoint(
    ledger: EvidenceLedger, anchor: dict[str, Any], tenant: UUID, mailbox: UUID, message: UUID
) -> None:
    try:
        value = {k: v for k, v in anchor.items() if k != "seal"}
        if (
            value["tenant_id"] != str(tenant)
            or value["mailbox_id"] != str(mailbox)
            or value["message_ref"] != str(message)
            or datetime.fromisoformat(value["expires_at"]) <= utc_now()
            or not hmac.compare_digest(
                str(anchor["seal"]),
                fingerprint(ledger._key(tenant), tenant, "history-anchor", value),
            )
        ):
            raise ValueError
        current = checkpoint(ledger, tenant, mailbox, message)
        if current["entries"][: len(value["entries"])] != value["entries"]:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise LedgerError("history_anchor_integrity_or_retention_failure") from None
