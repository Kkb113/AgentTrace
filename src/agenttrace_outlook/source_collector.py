"""Resumable audit evidence plus the owner-approved bounded POC correlation policy."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from .audit_source import AuditReader, publisher_snapshot
from .errors import SourceError
from .reader import MailReader
from .rule_store import RuleStore
from .sender_rules import qualify_exchange_send, sha
from .state import StateStore


class SenderCollector:
    def __init__(self, store: StateStore, reader: AuditReader, *, mail: MailReader | None = None):
        self.store, self.reader = store, reader
        self.rules = RuleStore(store)
        self.mail = mail
        self._publisher: dict[str, Any] | None = None
        self._publisher_expires = 0.0

    def _publisher_current(self) -> bool:
        now = self.store.clock().timestamp()
        if self._publisher and now < self._publisher_expires:
            return True
        self._publisher = None
        self._publisher = publisher_snapshot(self.store.config)
        self._publisher_expires = self.store.clock().timestamp() + 300
        return True

    def step(self) -> bool:
        self.rules.prepare()
        pending = self.rules.due()
        if pending is None:
            return False
        job, observation, snapshot = pending
        now = self.store.clock()
        self.store.heartbeat()
        if now >= observation.observed_at + timedelta(hours=24):
            self.rules.capture(
                job, observation, status="unavailable", reason="late_observation_window_closed"
            )
            self.rules.update(job, stage="closed")
            return True
        source = self.store.config.sender_source
        assert source is not None
        try:
            self._publisher_current()
            sent = datetime.fromisoformat(snapshot["sentDateTime"])
            if sent.tzinfo is None:
                raise SourceError("source_timestamp_invalid")
            if job["stage"] == "new":
                query_id = self.reader.create(sent)
                self.rules.update(job, stage="poll", query_id=query_id, delay=30)
                self.rules.capture(
                    {**job, "generation": job["generation"] + 1},
                    observation,
                    status="pending",
                    reason="audit_search_pending",
                )
            elif job["stage"] == "poll":
                result = self.reader.query(job["query_id"])
                if (
                    datetime.fromisoformat(result.get("filterStartDateTime", ""))
                    != sent - timedelta(minutes=2)
                    or datetime.fromisoformat(result.get("filterEndDateTime", ""))
                    != sent + timedelta(minutes=2)
                    or result.get("operationFilters") != ["Send"]
                    or [v.lower() for v in result.get("recordTypeFilters", [])] != ["exchangeitem"]
                    or [v.lower() for v in result.get("userPrincipalNameFilters", [])]
                    != [source.mailbox_address.lower()]
                    or str(result.get("id")) != job["query_id"]
                ):
                    raise SourceError("audit_query_scope_mismatch")
                if result.get("status") in {"failed", "cancelled"}:
                    raise SourceError("audit_query_failed")
                if result.get("status") not in {"notStarted", "running", "succeeded"}:
                    raise SourceError("audit_query_state_unsupported")
                self.rules.update(
                    job,
                    stage="records" if result.get("status") == "succeeded" else "poll",
                    query_id=job["query_id"],
                    delay=0 if result.get("status") == "succeeded" else 30,
                )
            elif job["stage"] == "records":
                result = self.reader.records(job["query_id"], job["cursor"])
                rows = result.get("value")
                if not isinstance(rows, list) or len(rows) > 1000:
                    raise SourceError("audit_page_invalid")
                records = json.loads(job["records"])
                for row in rows:
                    if not isinstance(row, dict):
                        raise SourceError("audit_record_invalid")
                    data = row.get("auditData", {})
                    if isinstance(data, str):
                        data = json.loads(data)
                    if not isinstance(data, dict):
                        raise SourceError("audit_record_invalid")
                    item = data.get("Item", {})
                    if isinstance(item, dict) and item.get("InternetMessageId") == snapshot.get(
                        "internetMessageId"
                    ):
                        records.append({**row, "auditData": data})
                if len(records) > 1000:
                    raise SourceError("audit_ambiguous_population")
                cursor = result.get("@odata.nextLink")
                if cursor:
                    self.reader.validate_page(job["query_id"], cursor)
                    if cursor == job["cursor"]:
                        raise SourceError("audit_page_loop")
                    self.rules.update(
                        job,
                        stage="records",
                        query_id=job["query_id"],
                        cursor=cursor,
                        records=records,
                    )
                else:
                    status, reason, refs = qualify_exchange_send(
                        records,
                        tenant=str(self.store.config.scope.tenant_id),
                        mailbox=source.mailbox_address,
                        mailbox_guid=str(source.exchange_mailbox_guid),
                        message_id=snapshot["internetMessageId"],
                        sent_at=sent,
                        publisher_current=self._publisher_current(),
                    )
                    publisher_ref = "publisher-sha256:" + sha(self._publisher)
                    declarations = [
                        r["value"].strip().lower()
                        for r in snapshot.get("internetMessageHeaders", [])
                        if r.get("name", "").lower() == "x-ai-generated"
                    ]
                    if (
                        status == "verified_enrolled_send"
                        and declarations == ["mcp-office365"]
                        and self.mail is not None
                    ):
                        self.rules.update(
                            job, stage="sent", query_id=job["query_id"], records=records
                        )
                        return True
                    self.rules.capture(
                        job,
                        observation,
                        status=status,
                        reason=reason,
                        refs=(*refs, publisher_ref),
                        raw={
                            "records": records,
                            "publisher": self._publisher,
                            "query_id": job["query_id"],
                        },
                    )
                    self.rules.update(job, stage="new", delay=source.refresh_seconds)
            elif job["stage"] == "sent":
                if self.mail is None:
                    raise SourceError("mail_correlation_reader_unavailable")
                result = self.mail.message_copies(snapshot["internetMessageId"], job["cursor"])
                rows = result.get("value")
                if not isinstance(rows, list) or len(rows) > 1000:
                    raise SourceError("message_correlation_page_invalid")
                records = json.loads(job["records"])
                for row in rows:
                    if (
                        not isinstance(row, dict)
                        or row.get("internetMessageId") != snapshot["internetMessageId"]
                        or not isinstance(row.get("id"), str)
                    ):
                        raise SourceError("message_correlation_page_invalid")
                    records.append(
                        {
                            "__agenttrace_copy_candidate": {
                                key: row.get(key)
                                for key in (
                                    "id",
                                    "parentFolderId",
                                    "isDraft",
                                    "internetMessageId",
                                    "sentDateTime",
                                )
                            }
                        }
                    )
                if len(records) > 1000:
                    raise SourceError("ambiguous_message_copy_population")
                cursor = result.get("@odata.nextLink")
                if cursor:
                    if cursor == job["cursor"]:
                        raise SourceError("message_correlation_page_loop")
                    # MailReader validates the retained continuation before it is used.
                    self.rules.update(
                        job, stage="sent", query_id=job["query_id"], cursor=cursor, records=records
                    )
                else:
                    audits = [r for r in records if "__agenttrace_copy_candidate" not in r]
                    copies = {
                        r["__agenttrace_copy_candidate"]["id"]: r["__agenttrace_copy_candidate"]
                        for r in records
                        if "__agenttrace_copy_candidate" in r
                    }
                    sent_folder = self.mail.well_known("sentitems")["id"]
                    sent_items = [
                        r
                        for r in copies.values()
                        if r.get("parentFolderId") == sent_folder and r.get("isDraft") is False
                    ]
                    received = [
                        r for r in copies.values() if r.get("parentFolderId") != sent_folder
                    ]
                    good = (
                        len(copies) == 2
                        and len(sent_items) == len(received) == 1
                        and received[0]["id"] == observation.message_id
                        and received[0].get("isDraft") is False
                        and sent_items[0].get("sentDateTime") == snapshot.get("sentDateTime")
                        and received[0].get("sentDateTime") == snapshot.get("sentDateTime")
                    )
                    status, reason, refs = qualify_exchange_send(
                        audits,
                        tenant=str(self.store.config.scope.tenant_id),
                        mailbox=source.mailbox_address,
                        mailbox_guid=str(source.exchange_mailbox_guid),
                        message_id=snapshot["internetMessageId"],
                        sent_at=sent,
                        publisher_current=self._publisher_current(),
                    )
                    self.rules.capture(
                        job,
                        observation,
                        status=status if good else "conflicting",
                        reason=reason if good else "message_copy_collision_or_context_conflict",
                        refs=(
                            *refs,
                            "publisher-sha256:" + sha(self._publisher),
                            "correlation-sha256:" + sha(list(copies.values())),
                        ),
                        receipt_context="corroborated_scope_messageid_time"
                        if good and status == "verified_enrolled_send"
                        else "unqualified",
                        raw={
                            "records": audits,
                            "publisher": self._publisher,
                            "query_id": job["query_id"],
                            "message_copies": list(copies.values()),
                        },
                    )
                    self.rules.update(job, stage="new", delay=source.refresh_seconds)
            return True
        except (ValueError, TypeError, KeyError):
            error = SourceError("audit_source_shape_invalid")
        except SourceError as caught:
            error = caught
        attempts = int(job["attempts"]) + 1
        reason = error.code
        force_block = error.retry_after >= 3600
        if force_block:
            reason = "retry_after_requires_operator"
        self.rules.capture(job, observation, status="unavailable", reason=reason)
        self.rules.update(
            job,
            stage="blocked"
            if force_block or not error.retryable or attempts >= self.store.config.max_attempts
            else job["stage"],
            query_id=job["query_id"],
            cursor=job["cursor"],
            records=json.loads(job["records"]),
            delay=max(30, error.retry_after),
            error=reason,
            attempts=attempts,
        )
        return True
