"""Compile Bicep and check foundation defaults without provisioning anything."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version = json.loads((ROOT / "config/toolchain.json").read_text())["bicep"]["version"]
    executable = (
        ROOT / "work/tools" / ("bicep-" + version) / ("bicep.exe" if os.name == "nt" else "bicep")
    )
    output = ROOT / "work/infra"
    output.mkdir(parents=True, exist_ok=True)
    extraction = ROOT / "work/dotnet-bundle"
    extraction.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, DOTNET_BUNDLE_EXTRACT_BASE_DIR=str(extraction))
    for source in sorted((ROOT / "infra/bicep").rglob("*.bicep")):
        result = subprocess.run(
            [
                str(executable),
                "build",
                str(source),
                "--outfile",
                str(output / (source.stem + ".json")),
            ],
            check=False,
            shell=False,
            env=environment,
        )
        if result.returncode:
            return result.returncode
    result = subprocess.run(
        [
            str(executable),
            "build-params",
            str(ROOT / "infra/bicep/validation.bicepparam"),
            "--outfile",
            str(output / "validation.parameters.json"),
        ],
        check=False,
        shell=False,
        env=environment,
    )
    if result.returncode:
        return result.returncode
    template = json.loads((output / "main.json").read_text(encoding="utf-8-sig"))
    parameters = template["parameters"]
    assert parameters["enableProvisioning"]["defaultValue"] is False
    assert parameters["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert parameters["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in template["resources"])
    access = json.loads((output / "access-sandbox.json").read_text(encoding="utf-8-sig"))
    assert access["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert access["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert access["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in access["resources"])
    notifications = json.loads(
        (output / "notification-transport.json").read_text(encoding="utf-8-sig")
    )
    assert notifications["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert notifications["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert notifications["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in notifications["resources"])
    graph = json.loads((output / "graph-activity-logging.json").read_text(encoding="utf-8-sig"))
    assert graph["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert graph["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert graph["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in graph["resources"])
    tables = [
        r
        for r in graph["resources"]
        if r["type"] == "Microsoft.OperationalInsights/workspaces/tables"
    ]
    assert len(tables) == 2
    assert all(
        table["properties"]["retentionInDays"] == table["properties"]["totalRetentionInDays"] == 7
        for table in tables
    )
    assert graph["parameters"]["enableErrorDiagnostics"]["defaultValue"] is False
    rule = next(
        r for r in graph["resources"] if r["type"] == "Microsoft.Insights/dataCollectionRules"
    )
    assert rule["kind"] == "WorkspaceTransforms"
    assert "outputStream" not in json.dumps(rule["properties"]["dataFlows"])
    diagnostics = next(
        r for r in graph["resources"] if r["type"] == "Microsoft.Insights/diagnosticSettings"
    )
    assert diagnostics["properties"]["logs"] == [{"category": "LogErrors", "enabled": True}]
    canary = json.loads((output / "graph-route-canary.json").read_text(encoding="utf-8-sig"))
    assert canary["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert canary["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert canary["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in r for r in canary["resources"])
    canary_table = next(r for r in canary["resources"] if r["type"].endswith("/tables"))
    assert (
        canary_table["properties"]["retentionInDays"]
        == canary_table["properties"]["totalRetentionInDays"]
        == 7
    )
    assert {c["name"] for c in canary_table["properties"]["schema"]["columns"]} == {
        "TimeGenerated",
        "CanaryId",
        "ProbeKind",
    }
    canary_rule = next(
        r for r in canary["resources"] if r["type"] == "Microsoft.Insights/dataCollectionRules"
    )
    assert canary_rule["kind"] == "Direct"
    canary_grant = next(
        r for r in canary["resources"] if r["type"] == "Microsoft.Authorization/roleAssignments"
    )
    assert canary_grant["properties"]["principalType"] == "User"
    assert "dataCollectionRules" in canary_grant["scope"]
    archive = json.loads((output / "graph-archive-diagnostic.json").read_text(encoding="utf-8-sig"))
    assert archive["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert archive["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert archive["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in r for r in archive["resources"])
    account = next(
        r for r in archive["resources"] if r["type"] == "Microsoft.Storage/storageAccounts"
    )
    assert account["sku"]["name"] == "Standard_LRS"
    assert account["properties"]["allowSharedKeyAccess"] is False
    assert account["properties"]["allowBlobPublicAccess"] is False
    assert account["properties"]["supportsHttpsTrafficOnly"] is True
    assert account["properties"]["minimumTlsVersion"] == "TLS1_2"
    firewall = account["properties"]["networkAcls"]
    assert firewall["defaultAction"] == "Deny" and firewall["bypass"] == "AzureServices"
    assert len(firewall["ipRules"]) == 1
    expiry = next(r for r in archive["resources"] if r["type"].endswith("/managementPolicies"))
    retention = expiry["properties"]["policy"]["rules"][0]["definition"]
    assert retention["actions"]["baseBlob"]["delete"]["daysAfterModificationGreaterThan"] == 7
    assert retention["filters"]["prefixMatch"] == ["insights-logs-microsoftgraphactivitylogs/"]
    assert not any(
        r["type"] == "Microsoft.Insights/diagnosticSettings" for r in archive["resources"]
    )
    print(
        json.dumps(
            {
                "bicep_modules_compiled": len(list((ROOT / "infra/bicep").rglob("*.bicep"))),
                "parameters_compiled": True,
                "resources_provisioned": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
