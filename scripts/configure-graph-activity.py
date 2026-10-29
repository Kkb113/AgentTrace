"""Deploy isolated filtered Graph logging and enable only its tenant log category."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from deployment_review import review_changes

from agenttrace_feasibility.audit import CLAUDE_CONNECTOR_APP_ID
from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_ingestion.activity_diagnostics import error_minimization_transform
from agenttrace_ingestion.activity_policy import ActivityScope

ROOT = Path(__file__).resolve().parents[1]
SETTING = "AgentTraceGraphActivity"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    baseline = ROOT / "work/private/secure-access"
    directory = ROOT / "work/private/graph-activity"
    config = json.loads(
        (baseline / "sandbox-settings.private.json").read_text(encoding="utf-8-sig")
    )
    identities = json.loads((baseline / "workload-identities.private.json").read_text())
    preflight = json.loads((directory / "preflight-summary.private.json").read_text())
    if (
        not (preflight["tenant_p1_enabled"] or preflight["tenant_p2_enabled"])
        or not preflight["tenant_diagnostic_read_succeeded"]
    ):
        raise RuntimeError("graph_logging_license_and_admin_preflight_required")
    collectors = frozenset(
        UUID(identities[n]["application"]["appId"]) for n in ["mail-collector", "audit-collector"]
    )
    scope = ActivityScope(
        UUID(config["tenant"]),
        UUID(config["operator_id"]),
        collectors | {UUID(CLAUDE_CONNECTOR_APP_ID)},
        collectors,
    )

    def az(label, commands, timeout=180):
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
            timeout=timeout,
        )
        (directory / (label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / (label + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError("graph_logging_configuration_failed_see_private_diagnostics")
        try:
            return json.loads(result.stdout.decode("utf-8")) if result.stdout.strip() else {}
        except UnicodeDecodeError:
            return json.loads(result.stdout.decode("cp1252"))

    inventory = az("resources-before", ["resource", "list", "--resource-group", "kb-agentdemo"])
    role = az(
        "log-data-reader-role",
        ["role", "definition", "list", "--name", "Log Analytics Data Reader"],
    )
    if len(role) != 1:
        raise RuntimeError("exact_log_data_reader_role_required")
    params = {
        "enableProvisioning": True,
        "readerPrincipalId": identities["audit-collector"]["service_principal"]["id"],
        "logDataReaderRoleId": role[0]["id"],
        "transformationKql": scope.transform(),
        "enableErrorDiagnostics": True,
        "errorTransformationKql": error_minimization_transform(),
        "attachExistingTransformation": any(
            r["type"].lower() == "microsoft.insights/datacollectionrules"
            and r.get("tags", {}).get("purpose") == "filtered-graph-activity"
            for r in inventory
        ),
    }
    parameter_file = directory / "graph-logging.parameters.private.json"
    parameter_file.write_text(
        json.dumps({"parameters": {k: {"value": v} for k, v in params.items()}}, indent=2)
    )
    template = ROOT / "work/infra/graph-activity-logging.json"
    common = [
        "--resource-group",
        "kb-agentdemo",
        "--name",
        "agenttrace-graph-activity",
        "--template-file",
        str(template),
        "--parameters",
        "@" + str(parameter_file),
    ]
    preview = az(
        "graph-logging-what-if",
        ["deployment", "group", "what-if", *common, "--no-pretty-print"],
        300,
    )
    review_changes(
        preview,
        inventory,
        "/subscriptions/" + config["subscription"] + "/resourceGroups/kb-agentdemo",
    )
    print(
        json.dumps(
            {
                "what_if_reviewed": True,
                "apply": args.apply,
                "new_compute": False,
                "retention_days": 7,
                "daily_ingestion_safeguard_gb": 0.1,
            }
        ),
        flush=True,
    )
    if not args.apply:
        return
    deployment = az(
        "graph-logging-deployment",
        ["deployment", "group", "create", *common, "--mode", "Incremental"],
        600,
    )
    settings = {k: v["value"] for k, v in deployment["properties"]["outputs"].items()}
    attach = directory / "workspace-rule-attachment.private.json"
    attach.write_text(
        json.dumps(
            {
                "properties": {
                    "defaultDataCollectionRuleResourceId": settings["transformationRuleId"]
                }
            }
        )
    )
    attached = az(
        "workspace-rule-attached",
        [
            "rest",
            "--method",
            "patch",
            "--url",
            "https://management.azure.com"
            + settings["workspaceResourceId"]
            + "?api-version=2023-09-01",
            "--body",
            "@" + str(attach),
        ],
    )
    if (
        attached["properties"].get("defaultDataCollectionRuleResourceId")
        != settings["transformationRuleId"]
    ):
        raise RuntimeError("workspace_transformation_not_attached")
    # Entra diagnostics are tenant-scoped; all billable destinations stay in kb-agentdemo.
    url = (
        "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings/"
        + SETTING
        + "?api-version=2017-04-01"
    )
    existing = az(
        "diagnostics-before-enable",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings?api-version=2017-04-01",
        ],
    )
    prior = next((s for s in existing.get("value", []) if s["name"] == SETTING), None)
    expected = {
        "workspaceId": settings["workspaceResourceId"],
        "logs": [
            {
                "category": "MicrosoftGraphActivityLogs",
                "enabled": True,
                "retentionPolicy": {"enabled": False, "days": 0},
            }
        ],
    }
    if prior:
        properties = prior["properties"]
        if (
            str(properties.get("workspaceId", "")).lower()
            != settings["workspaceResourceId"].lower()
            or {entry["category"] for entry in properties.get("logs", []) if entry["enabled"]}
            != {"MicrosoftGraphActivityLogs"}
            or properties.get("storageAccountId")
            or properties.get("eventHubAuthorizationRuleId")
        ):
            raise RuntimeError("existing_named_diagnostic_setting_requires_review")
    body = directory / "diagnostic-setting-request.private.json"
    body.write_text(json.dumps({"properties": expected}))
    if not prior:
        az(
            "graph-diagnostic-setting",
            ["rest", "--method", "put", "--url", url, "--body", "@" + str(body)],
        )
    previous_path = directory / "logging-settings.private.json"
    previous = json.loads(previous_path.read_text()) if previous_path.is_file() else {}
    settings.update(
        {
            "enabled_at": previous.get("enabled_at") or datetime.now(UTC).isoformat(),
            "source_initialized": previous.get("source_initialized", False),
            "tenant_id": str(scope.tenant),
            "pilot_user_id": str(scope.pilot_user),
            "clients": [str(v) for v in sorted(scope.clients, key=str)],
            "collector_clients": [str(v) for v in sorted(collectors, key=str)],
            "reader_client_id": identities["audit-collector"]["application"]["appId"],
            "reader_thumbprint": identities["audit-collector"]["certificate"]["thumbprint"],
            "diagnostic_setting_name": SETTING,
            "enabled": True,
            "error_diagnostics_enabled": True,
        }
    )
    (directory / "logging-settings.private.json").write_text(json.dumps(settings, indent=2))
    print(
        json.dumps(
            {
                "graph_diagnostic_category_enabled": True,
                "dedicated_pay_as_you_go_workspace": True,
                "new_mail_permissions": False,
            }
        )
    )


if __name__ == "__main__":
    main()
