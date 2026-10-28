"""Read-only licensing, directory-role and logging-destination preflight."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]


def main():
    baseline = ROOT / "work/private/secure-access"
    output = ROOT / "work/private/graph-activity"
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads(
        (baseline / "sandbox-settings.private.json").read_text(encoding="utf-8-sig")
    )
    if config["resource_group"] != "kb-agentdemo" or config["region"] != "eastus":
        raise RuntimeError("approved_graph_logging_target_required")

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
            timeout=120,
        )
        (output / (label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (output / (label + ".error.private.txt")).write_bytes(result.stderr)
            return None
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except UnicodeDecodeError:
            return json.loads(result.stdout.decode("cp1252"))

    skus = az(
        "tenant-license-inventory",
        ["rest", "--method", "get", "--url", "https://graph.microsoft.com/v1.0/subscribedSkus"],
    )
    license_details = az(
        "operator-licenses",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://graph.microsoft.com/v1.0/users/" + config["operator_id"] + "/licenseDetails",
        ],
    )
    roles = az(
        "operator-directory-roles",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://graph.microsoft.com/v1.0/users/"
            + config["operator_id"]
            + "/transitiveMemberOf/microsoft.graph.directoryRole?$select=displayName,roleTemplateId",
        ],
    )
    diagnostics = az(
        "tenant-diagnostic-settings",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings?api-version=2017-04-01",
        ],
    )
    categories = az(
        "tenant-diagnostic-categories",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettingsCategories?api-version=2017-04-01",
        ],
    )
    workspaces = az(
        "group-workspaces",
        ["monitor", "log-analytics", "workspace", "list", "--resource-group", "kb-agentdemo"],
    )
    az(
        "group-effective-role-assignments",
        [
            "role",
            "assignment",
            "list",
            "--assignee",
            config["operator_id"],
            "--scope",
            "/subscriptions/" + config["subscription"] + "/resourceGroups/kb-agentdemo",
            "--include-inherited",
        ],
    )
    enabled = []
    for sku in (skus or {}).get("value", []):
        if sku.get("capabilityStatus") == "Enabled":
            enabled += [
                p["servicePlanName"]
                for p in sku.get("servicePlans", [])
                if p.get("provisioningStatus") == "Success"
            ]
    assigned = [
        p["servicePlanName"]
        for lic in (license_details or {}).get("value", [])
        for p in lic.get("servicePlans", [])
        if p.get("provisioningStatus") == "Success"
    ]
    summary = {
        "tenant_license_read_succeeded": skus is not None,
        "tenant_p1_enabled": "AAD_PREMIUM" in enabled,
        "tenant_p2_enabled": "AAD_PREMIUM_P2" in enabled,
        "operator_p1_assigned": "AAD_PREMIUM" in assigned,
        "operator_p2_assigned": "AAD_PREMIUM_P2" in assigned,
        "directory_roles": [r["displayName"] for r in (roles or {}).get("value", [])],
        "tenant_diagnostic_read_succeeded": diagnostics is not None,
        "existing_diagnostic_settings": len((diagnostics or {}).get("value", [])),
        "graph_category_discovery_confirmed": any(
            c.get("name") == "MicrosoftGraphActivityLogs"
            for c in (categories or {}).get("value", [])
        ),
        "eastus_workspaces_in_group": sum(
            w.get("location") == "eastus" for w in (workspaces or [])
        ),
        "resources_created": 0,
    }
    (output / "preflight-summary.private.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
