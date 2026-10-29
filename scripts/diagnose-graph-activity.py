"""Read-only Graph routing diagnostics; keep identifiers and raw responses private."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener
from uuid import uuid4

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_foundation.mail_reader import NoRedirect
from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.activity_diagnostics import (
    aggregate_row_count,
    delivery_observation,
    error_minimization_transform,
    summarize_metrics,
)
from agenttrace_ingestion.activity_runtime import load_activity

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="Issue traceable GET-only controls")
    args = parser.parse_args()
    directory = ROOT / "work/private/graph-activity"
    config = json.loads(
        (ROOT / "work/private/secure-access/sandbox-settings.private.json").read_text(
            encoding="utf-8-sig"
        )
    )
    identities = json.loads(
        (ROOT / "work/private/secure-access/workload-identities.private.json").read_text()
    )
    collector, settings = load_activity(ROOT)

    def az(label, commands):
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                *commands,
                "--subscription",
                config["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=90,
        )
        (directory / ("diagnostic-" + label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / ("diagnostic-" + label + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError("diagnostic_read_failed_see_private_capture")
        return json.loads(result.stdout)

    organization = az(
        "organization",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://graph.microsoft.com/v1.0/organization?$select=id,tenantType",
        ],
    )
    graph_table = az(
        "graph-table-protection",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com"
            + str(settings["workspaceResourceId"])
            + "/tables/MicrosoftGraphActivityLogs?api-version=2025-02-01",
        ],
    )
    workspace = az(
        "workspace-authorization",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com"
            + str(settings["workspaceResourceId"])
            + "?api-version=2025-02-01",
        ],
    )
    categories = az(
        "dcr-log-categories",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com"
            + str(settings["transformationRuleId"])
            + "/providers/Microsoft.Insights/diagnosticSettingsCategories?api-version=2021-05-01-preview",
        ],
    )
    metrics = []
    metric_failures = 0
    for label, names, aggregation in [
        (
            "volume-metrics",
            "RowsReceived_Count,RowsDropped_Count,UncompressedBytesIn,UncompressedBytesOut",
            "Total",
        ),
        ("error-metrics", "TransformationErrors_Count", "Count"),
    ]:
        parameters = {
            "api-version": "2018-01-01",
            "metricnames": names,
            "timespan": str(settings["enabled_at"]).replace("+00:00", "Z")
            + "/"
            + datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "interval": "PT5M",
            "aggregation": aggregation,
        }
        try:
            response = az(
                label,
                [
                    "rest",
                    "--method",
                    "get",
                    "--url",
                    "https://management.azure.com"
                    + str(settings["transformationRuleId"])
                    + "/providers/Microsoft.Insights/metrics?"
                    + urlencode(parameters),
                ],
            )
            metrics += summarize_metrics(response, aggregation.lower())
        except RuntimeError:
            metric_failures += 1
    redaction_query = (
        "datatable(TimeGenerated:datetime, OperationName:string, InputStreamId:string, Message:string)["
        "datetime(2026-01-01), 'Transformation', 'Microsoft-Table-MicrosoftGraphActivityLogs', 'column synthetic-private-canary missing', "
        "datetime(2026-01-01), 'Ingestion', 'untrusted-stream-canary', 'synthetic-private-canary', "
        "datetime(2026-01-01), 'untrusted-operation-canary', 'untrusted-stream-canary', 'transform synthetic-private-canary'"
        "]" + error_minimization_transform()[len("source") :]
    )
    redaction_result = collector.transport.request(
        "POST",
        f"https://api.loganalytics.azure.com/v1/workspaces/{collector.workspace}/query",
        body={"query": redaction_query},
    )
    (directory / "diagnostic-error-redaction-test.private.json").write_text(
        json.dumps(redaction_result)
    )
    redaction_table = redaction_result["tables"][0]
    redaction_columns = [c["name"] for c in redaction_table["columns"]]
    redacted = [dict(zip(redaction_columns, r, strict=True)) for r in redaction_table["rows"]]
    redaction_passed = len(redacted) == 3 and all(
        r["Message"]
        in {"schema_or_column_error", "redacted_processing_error", "transformation_error"}
        and r["InputStreamId"] in {"Microsoft-Table-MicrosoftGraphActivityLogs", "redacted_stream"}
        and r["OperationName"] in {"Ingestion", "Transformation", "Unknown"}
        for r in redacted
    )
    query = collector.transport.request(
        "POST",
        f"https://api.loganalytics.azure.com/v1/workspaces/{collector.workspace}/query",
        body={"query": "MicrosoftGraphActivityLogs | summarize Rows=count()"},
    )
    rows = aggregate_row_count(query)
    error_rows = None
    unredacted_error_rows = None
    if settings.get("error_diagnostics_enabled"):
        error_query = directory / "diagnostic-error-query-request.private.json"
        error_query.write_text(
            json.dumps(
                {
                    "query": "DCRLogErrors | summarize Rows=count(), Unexpected=countif(Message !in ('schema_or_column_error','transformation_error','authorization_error','throttled','redacted_processing_error'))"
                }
            )
        )
        try:
            error_result = az(
                "error-query",
                [
                    "rest",
                    "--method",
                    "post",
                    "--url",
                    "https://api.loganalytics.azure.com/v1/workspaces/"
                    + str(collector.workspace)
                    + "/query",
                    "--resource",
                    "https://api.loganalytics.io",
                    "--body",
                    "@" + str(error_query),
                ],
            )
            error_rows, unredacted_error_rows = error_result["tables"][0]["rows"][0]
        except RuntimeError:
            pass
    observations = []
    if args.probe:
        identity = identities["mail-collector"]
        provider = CertificateTokenProvider(
            config["tenant"],
            identity["application"]["appId"],
            identity["certificate"]["thumbprint"],
            ROOT / "scripts/manage-workload-certificate.ps1",
        )
        opener = build_opener(NoRedirect())
        for label, path in [
            ("directory_organization_permission_control", "organization?$select=id"),
            ("directory_user_permission_control", "users/" + config["mailbox_id"] + "?$select=id"),
        ]:
            nonce = str(uuid4())
            headers = {
                "Authorization": "Bearer " + provider.token("https://graph.microsoft.com"),
                "client-request-id": nonce,
                "return-client-request-id": "true",
            }
            at = datetime.now(UTC).isoformat()
            try:
                with opener.open(
                    Request("https://graph.microsoft.com/v1.0/" + path, headers=headers),
                    timeout=20,
                ) as result:
                    status, response_headers = result.status, result.headers
                    result.read(4096)
            except HTTPError as error:
                status, response_headers = error.code, error.headers
                error.close()
            observations.append(
                {
                    "label": label,
                    "client_request_id": nonce,
                    "request_id": response_headers.get("request-id"),
                    "server_date": response_headers.get("Date"),
                    "time": at,
                    "client_id": identity["application"]["appId"],
                    "http_status": status,
                    "expected_http_status": 403,
                    "expected_logged": True,
                }
            )
        probe_path = directory / "directory-control-probes.private.json"
        earlier = json.loads(probe_path.read_text()) if probe_path.exists() else []
        probe_path.write_text(json.dumps(earlier + observations, indent=2))
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "graph_rows": rows,
        "graph_table_protection_level": graph_table["properties"].get(
            "protectionLevel", "not_reported"
        ),
        "workspace_data_authorization_mode": workspace["properties"]
        .get("features", {})
        .get("dataAuthorizationMode", "not_reported"),
        "delivery_observation": delivery_observation(rows, metrics),
        "metrics": [asdict(m) for m in metrics],
        "metric_queries_unavailable": metric_failures,
        "error_minimization_passes_actual_azure_kql_test": redaction_passed,
        "dcr_error_log_rows": error_rows,
        "unexpected_error_text_rows": unredacted_error_rows,
        "workforce_tenant_matches_config": any(
            entry["id"] == config["tenant"] and entry["tenantType"] == "AAD"
            for entry in organization.get("value", [])
        ),
        "dcr_log_errors_category_available": any(
            entry["name"] == "LogErrors" for entry in categories.get("value", [])
        ),
        "read_only_directory_controls": [
            {
                "label": p["label"],
                "http_status": p["http_status"],
                "expected_http_status": p["expected_http_status"],
            }
            for p in observations
        ],
        "root_cause_established": False,
        "email_mutations": 0,
        "agent_send_verdict": "not_established_by_this_diagnostic",
    }
    (ROOT / "docs/evidence/graph-activity-diagnostics.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))


if __name__ == "__main__":
    main()
