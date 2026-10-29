"""Interpret delivery telemetry without converting missing samples into evidence."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricSummary:
    name: str
    sample_count: int
    total: float | None


def summarize_metrics(payload: dict[str, Any], aggregation: str) -> list[MetricSummary]:
    if aggregation not in {"total", "count"}:
        raise ValueError("unsupported_metric_aggregation")
    result = []
    for metric in payload.get("value", []):
        samples = []
        for series in metric.get("timeseries", []):
            for point in series.get("data", []):
                value = point.get(aggregation)
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("invalid_metric_measurement")
                if not math.isfinite(value) or value < 0:
                    raise ValueError("invalid_metric_measurement")
                samples.append(float(value))
        result.append(
            MetricSummary(metric["name"]["value"], len(samples), sum(samples) if samples else None)
        )
    return result


def delivery_observation(rows: int, metrics: list[MetricSummary]) -> str:
    """Describe observations only; missing telemetry cannot identify a fault owner."""
    if rows < 0:
        raise ValueError("invalid_graph_row_count")
    observed = {m.name: m.total for m in metrics if m.total is not None}
    if (observed.get("TransformationErrors_Count") or 0) > 0:
        return "transformation_errors_observed"
    if rows:
        return "graph_records_observed"
    if (observed.get("RowsReceived_Count") or 0) > 0:
        return "ingestion_observed_without_stored_graph_records"
    if "RowsReceived_Count" in observed:
        return "zero_received_in_observed_metric_samples"
    return "no_graph_records_and_no_received_metric_samples"


def aggregate_row_count(response: dict[str, Any]) -> int:
    tables = response.get("tables", [])
    if response.get("error") or len(tables) != 1:
        raise ValueError("invalid_diagnostic_aggregate_response")
    table = tables[0]
    if [c.get("name") for c in table.get("columns", [])] != ["Rows"]:
        raise ValueError("invalid_diagnostic_aggregate_response")
    rows = table.get("rows", [])
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError("invalid_diagnostic_aggregate_response")
    value = rows[0][0]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid_diagnostic_aggregate_response")
    return value


def error_minimization_transform() -> str:
    # Error strings can contain source values. Keep only a fixed diagnostic bucket,
    # the operation and an allowlisted stream name; no raw error text or request IDs.
    return (
        "source | project TimeGenerated, "
        "OperationName=iff(OperationName in ('Ingestion','Transformation'), OperationName, 'Unknown'), "
        "InputStreamId=iff(InputStreamId in ('Microsoft-Table-MicrosoftGraphActivityLogs','Microsoft-Table-DCRLogErrors'), InputStreamId, 'redacted_stream'), "
        "Message=case(Message contains 'column', 'schema_or_column_error', "
        "Message contains 'transform', 'transformation_error', "
        "Message contains 'auth', 'authorization_error', "
        "Message contains 'throttl', 'throttled', 'redacted_processing_error')"
    )


def route_toggle_payload(
    properties: dict[str, Any], workspace_resource_id: str, *, enabled: bool
) -> dict[str, Any]:
    """Refuse to change a route that includes any unrelated category/destination."""
    logs = properties.get("logs", [])
    if (
        str(properties.get("workspaceId", "")).lower() != workspace_resource_id.lower()
        or sum(entry.get("category") == "MicrosoftGraphActivityLogs" for entry in logs) != 1
        or any(
            entry.get("enabled") and entry.get("category") != "MicrosoftGraphActivityLogs"
            for entry in logs
        )
        or any(
            properties.get(key)
            for key in (
                "storageAccountId",
                "eventHubAuthorizationRuleId",
                "eventHubName",
                "serviceBusRuleId",
                "marketplacePartnerId",
            )
        )
        or any(entry.get("enabled") for entry in properties.get("metrics", []))
    ):
        raise ValueError("dedicated_graph_only_route_required")
    entries = [dict(entry) for entry in logs]
    for entry in entries:
        if entry.get("category") == "MicrosoftGraphActivityLogs":
            entry["enabled"] = enabled
    return {"properties": {"workspaceId": properties["workspaceId"], "logs": entries}}


def graph_route_enabled(properties: dict[str, Any]) -> bool:
    entries = [
        v for v in properties.get("logs", []) if v.get("category") == "MicrosoftGraphActivityLogs"
    ]
    if len(entries) != 1:
        raise ValueError("invalid_graph_route_enabled_state")
    enabled = entries[0].get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("invalid_graph_route_enabled_state")
    return enabled
