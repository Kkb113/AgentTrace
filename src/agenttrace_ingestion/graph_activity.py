"""Optional, explicitly configured Graph activity source; no logging is enabled here."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from .contracts import IngestionError, utc_now
from .mailbox import instant
from .store import IngestionStore
from .transport import MicrosoftTransport


class GraphActivityCollector:
    def __init__(
        self,
        store: IngestionStore,
        transport: MicrosoftTransport,
        source_ref: UUID,
        workspace: UUID,
        *,
        tenant: UUID,
        clients: set[UUID],
        collector_clients: set[UUID],
    ):
        if transport.host != "api.loganalytics.azure.com" or not clients:
            raise ValueError("explicit_graph_activity_workspace_and_clients_required")
        self.store, self.transport, self.source_ref, self.workspace = (
            store,
            transport,
            source_ref,
            workspace,
        )
        self.tenant, self.clients, self.collector_clients = tenant, clients, collector_clients
        self.partition = store.cipher.reference(str(source_ref), "graph-activity")

    def collect(self) -> int:
        lease = self.store.claim_checkpoint(self.source_ref, self.partition)
        if lease is None:
            return 0
        try:
            end = utc_now() - timedelta(minutes=5)  # Do not treat fresh log latency as absence.
            start = (
                lease.watermark - timedelta(minutes=15)
                if lease.watermark
                else end - timedelta(hours=1)
            )
            clients = ",".join("'" + str(c) + "'" for c in sorted(self.clients, key=str))
            query = (
                "MicrosoftGraphActivityLogs | where TimeGenerated between (datetime("
                + start.isoformat()
                + ") .. datetime("
                + end.isoformat()
                + ")) | where AadTenantId == '"
                + str(self.tenant)
                + "' | where AppId in ("
                + clients
                + ") | project TimeGenerated, RequestId, AppId, RequestMethod, RequestUri, ResponseStatusCode"
            )
            response = self.transport.request(
                "POST",
                f"https://api.loganalytics.azure.com/v1/workspaces/{self.workspace}/query",
                body={"query": query},
            )
            if response.get("error") or len(response.get("tables", [])) != 1:
                raise IngestionError("graph_activity_partial_or_invalid_response")
            table = response["tables"][0]
            columns = [c["name"] for c in table["columns"]]
            if set(columns) != {
                "TimeGenerated",
                "RequestId",
                "AppId",
                "RequestMethod",
                "RequestUri",
                "ResponseStatusCode",
            }:
                raise IngestionError("graph_activity_columns_invalid")
            if len(table["rows"]) >= 10_000:
                raise IngestionError("graph_activity_window_requires_split")
            count = 0
            with self.store.database.connect() as connection:
                self.store._checkpoint_fence(connection, lease)
                for row in table["rows"]:
                    record = dict(zip(columns, row, strict=True))
                    client = UUID(record["AppId"])
                    if client not in self.clients:
                        raise IngestionError("graph_activity_client_out_of_scope")
                    own = client in self.collector_clients
                    operation = (
                        "Send"
                        if record["RequestMethod"] == "POST"
                        and str(record["RequestUri"]).rstrip("/").endswith("/sendMail")
                        and 200 <= int(record["ResponseStatusCode"]) < 300
                        else "Read"
                        if own
                        else "Other"
                    )
                    ref = self.store.cipher.reference(
                        str(self.source_ref), str(record["RequestId"])
                    )
                    # Query URI may contain mailbox identifiers. Keep it encrypted;
                    # a successful API call still does not prove AI execution.
                    encrypted = self.store.cipher.seal(record, context="audit:" + str(ref))
                    count += int(
                        connection.execute(
                            "INSERT INTO ingest_audit_events(event_ref,source_ref,occurred_at,operation,collector_action,signal_eligible,evidence_cipher) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                            (
                                ref,
                                self.source_ref,
                                instant(record["TimeGenerated"]),
                                operation,
                                own,
                                operation == "Send" and not own,
                                encrypted,
                            ),
                        ).rowcount
                        == 1
                    )
                connection.execute(
                    "UPDATE ingest_checkpoints SET watermark=%s,coverage='current',reason_code='graph_activity_window_current',last_success=now(),lease=NULL,lease_until=NULL WHERE source_ref=%s AND partition_ref=%s",
                    (end, self.source_ref, self.partition),
                )
            return count
        except IngestionError as error:
            self.store.fail_checkpoint(lease, error)
            raise
