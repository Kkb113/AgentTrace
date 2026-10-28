"""Read-only Office 365 Exchange audit queries with resumable, overlapping windows."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

from .contracts import IngestionError, utc_now
from .mailbox import instant
from .store import IngestionStore
from .transport import MicrosoftTransport


def _strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(_strings(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_strings(v) for v in value)) if value else set()
    return set()


class ExchangeAuditCollector:
    ROOT = "https://graph.microsoft.com/v1.0/security/auditLog/queries"

    def __init__(
        self,
        store: IngestionStore,
        transport: MicrosoftTransport,
        source_ref: UUID,
        *,
        mailbox: str,
        collector_clients: set[str],
        allowed_message_ids: set[str],
    ):
        self.store, self.transport, self.source_ref = store, transport, source_ref
        self.mailbox, self.collector_clients, self.allowed_message_ids = (
            mailbox,
            collector_clients,
            allowed_message_ids,
        )
        self.partition = store.cipher.reference(str(source_ref), "exchange-audit")

    def collect(self, *, window_end: datetime | None = None) -> int:
        lease = self.store.claim_checkpoint(self.source_ref, self.partition)
        if lease is None:
            return 0
        try:
            end = window_end or utc_now()
            start = (
                lease.watermark - timedelta(minutes=15)
                if lease.watermark
                else end - timedelta(hours=24)
            )
            if lease.cursor:
                cursor = json.loads(lease.cursor)
                end = instant(cursor["end"])
            else:
                query = self.transport.request(
                    "POST",
                    self.ROOT,
                    body={
                        "displayName": "AgentTrace bounded synthetic detection evidence",
                        "filterStartDateTime": start.isoformat(),
                        "filterEndDateTime": end.isoformat(),
                        "recordTypeFilters": ["exchangeItem"],
                        "operationFilters": ["Send", "MailItemsAccessed"],
                        "userPrincipalNameFilters": [self.mailbox],
                    },
                )
                cursor = {
                    "query": self.ROOT + "/" + quote(str(query["id"]), safe=""),
                    "end": end.isoformat(),
                    "page": None,
                }
                self.store.commit_page(lease, [], json.dumps(cursor), final=False)
                return 0
            query_url = cursor["query"]
            parsed = urlsplit(query_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "graph.microsoft.com"
                or not parsed.path.startswith("/v1.0/security/auditLog/queries/")
                or parsed.fragment
            ):
                raise IngestionError("audit_cursor_out_of_scope")
            if not cursor.get("page"):
                state = self.transport.request("GET", query_url).get("status")
                if state in {"failed", "cancelled"}:
                    raise IngestionError("audit_query_failed")
                if state != "succeeded":
                    self.store.wait_checkpoint(lease, reason="audit_query_pending", seconds=10)
                    return 0
            page_url = cursor.get("page") or query_url + "/records?$top=100"
            if (
                urlsplit(page_url).netloc != "graph.microsoft.com"
                or urlsplit(page_url).scheme != "https"
                or urlsplit(page_url).path != urlsplit(query_url).path + "/records"
            ):
                raise IngestionError("audit_page_out_of_scope")
            page = self.transport.request("GET", page_url)
            records = page.get("value")
            if not isinstance(records, list) or len(records) > 1000:
                raise IngestionError("audit_page_invalid")
            with self.store.database.connect() as connection:
                self.store._checkpoint_fence(connection, lease)
                count = 0
                for record in records:
                    data = record.get("auditData") or {}
                    if isinstance(data, str):
                        data = json.loads(data)
                    client = str(data.get("AppId") or data.get("ClientAppId") or "")
                    collector_action = client in self.collector_clients
                    # Tenant-wide audit visibility is not equivalent to permission to
                    # retain arbitrary records. Keep only exact authorized message IDs
                    # or known collector accesses for access auditing.
                    exact_messages = self.allowed_message_ids.intersection(_strings(data))
                    if not collector_action and not exact_messages:
                        continue
                    operation = (
                        "Send"
                        if (record.get("operation") or data.get("Operation")) == "Send"
                        else "Read"
                        if collector_action
                        or (record.get("operation") or data.get("Operation")) == "MailItemsAccessed"
                        else "Other"
                    )
                    ref = self.store.cipher.reference(
                        str(self.source_ref), "audit:" + str(record["id"])
                    )
                    evidence = self.store.cipher.seal(
                        {
                            "record_id": str(record["id"]),
                            "operation": operation,
                            "client_id": client,
                            "exact_message_ids": sorted(exact_messages),
                            "request_id": data.get("RequestId"),
                            "session_id": data.get("SessionId"),
                            "actor": data.get("UserId"),
                            "logon_type": data.get("LogonType"),
                        },
                        context="audit:" + str(ref),
                    )
                    result = connection.execute(
                        "INSERT INTO ingest_audit_events(event_ref,source_ref,occurred_at,operation,collector_action,signal_eligible,evidence_cipher) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (
                            ref,
                            self.source_ref,
                            instant(record.get("createdDateTime") or data.get("CreationTime")),
                            operation,
                            collector_action,
                            operation == "Send" and not collector_action,
                            evidence,
                        ),
                    )
                    count += int(result.rowcount == 1)
                next_page = page.get("@odata.nextLink")
                cursor["page"] = next_page
                value = json.dumps(cursor) if next_page else ""
                encrypted = (
                    self.store.cipher.seal(
                        {"cursor": value}, context="cursor:" + str(self.partition)
                    )
                    if next_page
                    else None
                )
                connection.execute(
                    "UPDATE ingest_checkpoints SET cursor_cipher=%s,watermark=CASE WHEN %s THEN watermark ELSE %s END,coverage=%s,reason_code=%s,last_success=CASE WHEN %s THEN last_success ELSE now() END,lease=NULL,lease_until=NULL,next_attempt=now() WHERE source_ref=%s AND partition_ref=%s",
                    (
                        encrypted,
                        bool(next_page),
                        end,
                        "catching_up" if next_page else "current",
                        "audit_next_page" if next_page else "audit_window_current",
                        bool(next_page),
                        self.source_ref,
                        self.partition,
                    ),
                )
            return count
        except IngestionError as error:
            self.store.fail_checkpoint(
                lease, error, reset=error.code in {"audit_query_failed", "source_item_not_found"}
            )
            raise


class OptionalActivityCollector:
    """Keep unconfigured sources explicitly unavailable; never acquire new permissions."""

    def __init__(self, store: IngestionStore, source_ref: UUID, kind: str):
        if kind not in {"office_activity", "graph_activity"}:
            raise ValueError("unsupported_optional_activity_source")
        self.store, self.source_ref, self.kind = store, source_ref, kind

    def unavailable(self) -> None:
        partition = self.store.cipher.reference(str(self.source_ref), self.kind)
        lease = self.store.claim_checkpoint(self.source_ref, partition)
        if lease:
            self.store.fail_checkpoint(
                lease,
                IngestionError(
                    "office_activity_permission_not_configured"
                    if self.kind == "office_activity"
                    else "graph_activity_destination_not_configured",
                    retry_after=3600,
                ),
            )
