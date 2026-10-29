import pytest

from agenttrace_ingestion.activity_diagnostics import (
    MetricSummary,
    aggregate_row_count,
    delivery_observation,
    error_minimization_transform,
    graph_route_enabled,
    route_toggle_payload,
    summarize_metrics,
)


def metric(series):
    return {"value": [{"name": {"value": "RowsReceived_Count"}, "timeseries": series}]}


@pytest.mark.parametrize("series", [[], [{"data": []}], [{"data": [{"total": None}]}]])
def test_missing_ingestion_measurements_remain_unknown(series):
    result = summarize_metrics(metric(series), "total")
    assert result == [MetricSummary("RowsReceived_Count", 0, None)]
    assert delivery_observation(0, result) == "no_graph_records_and_no_received_metric_samples"


def test_actual_zero_and_nonzero_samples_are_distinguished_from_absence():
    result = summarize_metrics(metric([{"data": [{"total": 0}, {"total": None}]}]), "total")
    assert result == [MetricSummary("RowsReceived_Count", 1, 0.0)]
    assert delivery_observation(0, result) == "zero_received_in_observed_metric_samples"
    positive = summarize_metrics(metric([{"data": [{"total": 2}, {"total": 3}]}]), "total")
    assert positive[0].total == 5
    assert delivery_observation(0, positive) == "ingestion_observed_without_stored_graph_records"


@pytest.mark.parametrize("value", [True, "0", -1, float("nan"), float("inf")])
def test_malformed_measurements_never_become_healthy_zero(value):
    with pytest.raises(ValueError, match="invalid_metric_measurement"):
        summarize_metrics(metric([{"data": [{"total": value}]}]), "total")


def test_error_samples_override_an_apparently_working_stream():
    assert delivery_observation(1, []) == "graph_records_observed"
    assert (
        delivery_observation(1, [MetricSummary("TransformationErrors_Count", 1, 2)])
        == "transformation_errors_observed"
    )


@pytest.mark.parametrize(
    "response",
    [
        {"tables": []},
        {"error": {"code": "PartialError"}},
        {"tables": [{"columns": [{"name": "Rows"}], "rows": []}]},
    ],
)
def test_invalid_aggregate_responses_never_become_zero_records(response):
    with pytest.raises(ValueError, match="invalid_diagnostic_aggregate_response"):
        aggregate_row_count(response)


def test_valid_aggregate_counts_preserve_zero_and_positive_values():
    for count in [0, 1, 10]:
        assert (
            aggregate_row_count({"tables": [{"columns": [{"name": "Rows"}], "rows": [[count]]}]})
            == count
        )


def test_error_logging_never_projects_raw_error_text_or_identifiers():
    transform = error_minimization_transform()
    assert "Message=case(" in transform
    assert "redacted_processing_error" in transform and "redacted_stream" in transform
    assert "ClientRequestId" not in transform and "CorrelationId" not in transform


def test_route_refresh_only_changes_the_selected_category_enabled_flag():
    original = {
        "workspaceId": "/synthetic-workspace",
        "logs": [
            {
                "category": "MicrosoftGraphActivityLogs",
                "enabled": True,
                "retentionPolicy": {"enabled": False, "days": 0},
            }
        ],
    }
    disabled = route_toggle_payload(original, "/synthetic-workspace", enabled=False)
    assert disabled["properties"]["logs"][0]["enabled"] is False
    assert original["logs"][0]["enabled"] is True
    restored = route_toggle_payload(disabled["properties"], "/synthetic-workspace", enabled=True)
    assert restored["properties"] == original


def test_route_refresh_preserves_provider_expanded_disabled_categories():
    properties = {
        "workspaceId": "/synthetic-workspace",
        "logs": [
            {"category": "AuditLogs", "enabled": False},
            {"category": "MicrosoftGraphActivityLogs", "enabled": True},
        ],
    }
    result = route_toggle_payload(properties, "/synthetic-workspace", enabled=False)
    assert result["properties"]["logs"][0] == properties["logs"][0]
    assert result["properties"]["logs"][1]["enabled"] is False
    assert graph_route_enabled(properties) is True
    assert graph_route_enabled(result["properties"]) is False


@pytest.mark.parametrize(
    "change",
    [
        {"workspaceId": "/another-workspace"},
        {"storageAccountId": "/synthetic-archive"},
        {"eventHubAuthorizationRuleId": "/synthetic-stream"},
        {"logs": [{"category": "AuditLogs", "enabled": True}]},
        {
            "logs": [
                {"category": "MicrosoftGraphActivityLogs", "enabled": True},
                {"category": "AuditLogs", "enabled": True},
            ]
        },
    ],
)
def test_route_refresh_refuses_broader_or_different_diagnostic_routes(change):
    original = {
        "workspaceId": "/synthetic-workspace",
        "logs": [{"category": "MicrosoftGraphActivityLogs", "enabled": True}],
    }
    with pytest.raises(ValueError, match="dedicated_graph_only_route_required"):
        route_toggle_payload(original | change, "/synthetic-workspace", enabled=False)
