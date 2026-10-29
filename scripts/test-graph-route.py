"""Use one synthetic canary to test workspace ingestion independently of Graph export."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from uuid import uuid4

from deployment_review import review_changes

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_foundation.mail_reader import NoRedirect
from agenttrace_ingestion.activity_diagnostics import aggregate_row_count

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=300, choices=range(60, 601))
    args = parser.parse_args()
    directory = ROOT / "work/private/graph-activity"
    config = json.loads(
        (ROOT / "work/private/secure-access/sandbox-settings.private.json").read_text(
            encoding="utf-8-sig"
        )
    )
    settings = json.loads((directory / "logging-settings.private.json").read_text())

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
            timeout=180,
        )
        (directory / ("canary-" + label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / ("canary-" + label + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError("canary_command_failed_see_private_capture")
        return json.loads(result.stdout)

    group = "/subscriptions/" + config["subscription"] + "/resourceGroups/kb-agentdemo"
    if config["resource_group"] != "kb-agentdemo" or config["region"] != "eastus":
        raise RuntimeError("approved_canary_target_required")
    workspace = az(
        "workspace",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com"
            + settings["workspaceResourceId"]
            + "?api-version=2023-09-01",
        ],
    )
    if (
        not workspace["id"].lower().startswith(group.lower() + "/")
        or workspace.get("tags", {}).get("project") != "AgentTrace"
        or workspace["location"] != "eastus"
    ):
        raise RuntimeError("managed_graph_workspace_required")
    operator = az(
        "operator",
        ["rest", "--method", "get", "--url", "https://graph.microsoft.com/v1.0/me?$select=id"],
    )
    if operator["id"] != config["operator_id"]:
        raise RuntimeError("designated_canary_operator_required")
    publisher_role = az(
        "publisher-role", ["role", "definition", "list", "--name", "Monitoring Metrics Publisher"]
    )
    if len(publisher_role) != 1:
        raise RuntimeError("exact_metrics_publisher_role_required")
    parameter_file = directory / "route-canary.parameters.private.json"
    parameter_file.write_text(
        json.dumps(
            {
                "parameters": {
                    "enableProvisioning": {"value": True},
                    "workspaceName": {"value": settings["workspaceName"]},
                    "operatorPrincipalId": {"value": operator["id"]},
                    "metricsPublisherRoleId": {"value": publisher_role[0]["id"]},
                }
            }
        )
    )
    common = [
        "--resource-group",
        "kb-agentdemo",
        "--name",
        "agenttrace-route-canary",
        "--template-file",
        str(ROOT / "work/infra/graph-route-canary.json"),
        "--parameters",
        "@" + str(parameter_file),
    ]
    inventory = az("inventory", ["resource", "list", "--resource-group", "kb-agentdemo"])
    preview = az("what-if", ["deployment", "group", "what-if", *common, "--no-pretty-print"])
    review_changes(preview, inventory, group)
    print(
        json.dumps(
            {
                "canary_plan_reviewed": True,
                "apply": args.apply,
                "standing_compute": False,
                "operator_publish_scope": "synthetic_canary_dcr_only",
            }
        ),
        flush=True,
    )
    if not args.apply:
        return 0
    deployment = az(
        "deployment", ["deployment", "group", "create", *common, "--mode", "Incremental"]
    )
    rule_id = deployment["properties"]["outputs"]["ruleResourceId"]["value"]
    grant_id = deployment["properties"]["outputs"]["publisherGrantId"]["value"]
    grant = az(
        "publisher-grant",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com" + grant_id + "?api-version=2022-04-01",
        ],
    )
    grant_verified = (
        grant["properties"]["principalId"] == operator["id"]
        and grant["properties"]["scope"].lower() == rule_id.lower()
        and grant["properties"]["roleDefinitionId"].lower() == publisher_role[0]["id"].lower()
    )
    if not grant_verified:
        raise RuntimeError("canary_publish_grant_mismatch")
    rule = az(
        "rule",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com" + rule_id + "?api-version=2023-03-11",
        ],
    )
    endpoint = rule["properties"]["endpoints"]["logsIngestion"].rstrip("/")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.netloc.endswith(".ingest.monitor.azure.com")
        or parsed.port is not None
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("trusted_canary_ingestion_endpoint_required")
    token_result = subprocess.run(
        [
            *azure_cli_prefix(),
            "account",
            "get-access-token",
            "--subscription",
            config["subscription"],
            "--resource",
            "https://monitor.azure.com",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        capture_output=True,
        timeout=60,
    )
    if token_result.returncode:
        raise RuntimeError("canary_operator_token_unavailable")
    token = token_result.stdout.decode().strip()
    nonce = str(uuid4())
    request_nonce = str(uuid4())
    body = [
        {
            "TimeGenerated": datetime.now(UTC).isoformat(),
            "CanaryId": nonce,
            "ProbeKind": "synthetic-route-control",
        }
    ]
    url = (
        endpoint
        + "/dataCollectionRules/"
        + rule["properties"]["immutableId"]
        + "/streams/Custom-AgentTraceRouteCanary?api-version=2023-01-01"
    )
    request = Request(
        url,
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "x-ms-client-request-id": request_nonce,
        },
    )
    deadline = time.monotonic() + args.wait_seconds
    authorization_retries = 0
    while True:
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                status = response.status
                response.read(4096)
        except HTTPError as error:
            status = error.code
            (directory / "canary-ingestion-error.private.txt").write_bytes(error.read(8192))
            error.close()
        # A denied request accepted no canary. Allow bounded propagation time;
        # never retry an accepted or ambiguous write and create duplicate evidence.
        if status != 403 or time.monotonic() + 15 >= deadline:
            break
        authorization_retries += 1
        time.sleep(15)
    receipt = {
        "canary_id": nonce,
        "client_request_id": request_nonce,
        "ingestion_http_status": status,
        "sent_at": body[0]["TimeGenerated"],
    }
    receipt_path = directory / "canary-receipt.private.json"
    if receipt_path.exists():
        archive = directory / "earlier-canary-receipts.private.json"
        earlier = json.loads(archive.read_text()) if archive.exists() else []
        archive.write_text(json.dumps(earlier + [json.loads(receipt_path.read_text())], indent=2))
    receipt_path.write_text(json.dumps(receipt, indent=2))
    query_file = directory / "canary-query-request.private.json"
    query_file.write_text(
        json.dumps(
            {
                "query": "AgentTraceRouteCanary_CL | where CanaryId == '"
                + nonce
                + "' and ProbeKind == 'synthetic-route-control' | summarize Rows=count()"
            }
        )
    )
    count = 0
    while status in {200, 202, 204} and time.monotonic() < deadline:
        response = az(
            "query",
            [
                "rest",
                "--method",
                "post",
                "--url",
                "https://api.loganalytics.azure.com/v1/workspaces/"
                + settings["workspaceCustomerId"]
                + "/query",
                "--resource",
                "https://api.loganalytics.io",
                "--body",
                "@" + str(query_file),
            ],
        )
        count = aggregate_row_count(response)
        if count:
            break
        time.sleep(15)
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "ingestion_http_status": status,
        "exact_canary_rows": count,
        "workspace_ingestion_and_query_canary_passed": status in {200, 202, 204} and count == 1,
        "graph_publisher_verified_by_this_test": False,
        "contains_email_or_customer_data": False,
        "new_mail_permissions": False,
        "operator_canary_publish_grant_verified": grant_verified,
        "operator_publish_scope": "synthetic_canary_dcr_only",
        "authorization_propagation_retries": authorization_retries,
        "retention_days": 7,
    }
    (ROOT / "docs/evidence/graph-route-canary-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))
    return 0 if report["workspace_ingestion_and_query_canary_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
