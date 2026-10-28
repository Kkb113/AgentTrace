"""Optional, explicitly configured Graph activity source; no logging is enabled here."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from .activity_policy import minimal_request_uri, send_request_observed
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
        pilot_user: UUID | None = None,
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
        self.pilot_user = pilot_user
        self.partition = store.cipher.reference(str(source_ref), "graph-activity")

    def collect(self) -> int:
        lease = self.store.claim_checkpoint(self.source_ref, self.partition)
        if lease is None:
            return 0
        try:
            end = utc_now() - timedelta(minutes=5)  # Do not treat fresh log latency as absence.
            start = (
                lease.watermark - timedelta(hours=24)
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
                + ")"
            )
            if self.pilot_user:
                own_clients = ",".join(
                    "'" + str(c) + "'" for c in sorted(self.collector_clients, key=str)
                )
                query += (
                    " | where UserId == '"
                    + str(self.pilot_user)
                    + "' or AppId in ("
                    + own_clients
                    + ")"
                )
            query += " | project TimeGenerated, RequestId, AppId, RequestMethod, RequestUri, ResponseStatusCode | take 10001"
            response = self.transport.request(
                "POST",
                f"https://api.loganalytics.azure.com/v1/workspaces/{self.workspace}/query",
                body={"query": query},
            )
            if response.get("error") or len(response.get("tables", [])) != 1:
                raise IngestionError("graph_activity_partial_or_invalid_response")
            table = response["tables"][0]
            columns = [c["name"] for c in table["columns"]]
            if len(columns) != 6 or set(columns) != {
                "TimeGenerated",
                "RequestId",
                "AppId",
                "RequestMethod",
                "RequestUri",
                "ResponseStatusCode",
            }:
                raise IngestionError("graph_activity_columns_invalid")
            if len(table["rows"]) > 10_000:
                raise IngestionError("graph_activity_window_requires_split")
            count = 0
            with self.store.database.connect() as connection:
                self.store._checkpoint_fence(connection, lease)
                for row in table["rows"]:
                    record = dict(zip(columns, row, strict=True))
                    record["RequestUri"] = minimal_request_uri(str(record["RequestUri"]))
                    client = UUID(record["AppId"])
                    if client not in self.clients:
                        raise IngestionError("graph_activity_client_out_of_scope")
                    own = client in self.collector_clients
                    operation = (
                        "Send"
                        if send_request_observed(
                            str(record["RequestMethod"]),
                            str(record["RequestUri"]),
                            int(record["ResponseStatusCode"]),
                        )
                        else "Read"
                        if own and record["RequestMethod"] == "GET"
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
                    "UPDATE ingest_checkpoints SET watermark=%s,coverage=%s,reason_code=%s,last_success=now(),lease=NULL,lease_until=NULL,next_attempt=now()+interval '60 seconds' WHERE source_ref=%s AND partition_ref=%s",
                    (
                        end,
                        "current" if table["rows"] else "catching_up",
                        "graph_activity_window_observed"
                        if table["rows"]
                        else "graph_activity_delivery_pending",
                        self.source_ref,
                        self.partition,
                    ),
                )
            return count
        except IngestionError as error:
            self.store.fail_checkpoint(lease, error)
            raise
        except (ValueError, TypeError, KeyError, OverflowError):
            invalid_response = IngestionError("graph_activity_response_invalid")
            self.store.fail_checkpoint(lease, invalid_response)
            raise invalid_response from None
