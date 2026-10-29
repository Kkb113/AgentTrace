"""Run the owner-approved, bounded raw Graph archive diagnostic, then stop export."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deployment_review import review_changes

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]
CATEGORY = "MicrosoftGraphActivityLogs"
SETTING = "AgentTraceGraphArchiveProbe"
CONTAINER = "insights-logs-microsoftgraphactivitylogs"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=600, choices=range(60, 1801))
    parser.add_argument("--stop", action="store_true", help="Stop the saved archive route only")
    args = parser.parse_args()
    directory = ROOT / "work/private/graph-activity"
    config = json.loads(
        (ROOT / "work/private/secure-access/sandbox-settings.private.json").read_text(
            encoding="utf-8-sig"
        )
    )
    if config["resource_group"] != "kb-agentdemo" or config["region"] != "eastus":
        raise RuntimeError("approved_archive_target_required")

    def az(label, commands, *, absent_ok=False):
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
        (directory / ("archive-" + label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / ("archive-" + label + ".error.private.txt")).write_bytes(result.stderr)
            if absent_ok and b"ResourceNotFound" in result.stderr:
                return None
            raise RuntimeError("archive_command_failed_see_private_capture_" + label)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    url = (
        "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings/"
        + SETTING
        + "?api-version=2017-04-01"
    )
    group = "/subscriptions/" + config["subscription"] + "/resourceGroups/kb-agentdemo"

    def stop():
        body = json.loads((directory / "archive-off-request.private.json").read_text())
        destination = body["properties"]["storageAccountId"]
        if not destination.lower().startswith(
            group.lower() + "/providers/microsoft.storage/storageaccounts/atgraphdiag"
        ):
            raise RuntimeError("archive_stop_destination_not_managed")
        current = az("stop-current", ["rest", "--method", "get", "--url", url], absent_ok=True)
        if current is not None:
            properties = current["properties"]
            if (
                properties.get("storageAccountId", "").lower() != destination.lower()
                or properties.get("workspaceId")
                or properties.get("eventHubAuthorizationRuleId")
                or any(
                    r.get("enabled") and r.get("category") != CATEGORY for r in properties["logs"]
                )
            ):
                raise RuntimeError("archive_stop_route_changed_refusing_overwrite")
            az(
                "stopped",
                [
                    "rest",
                    "--method",
                    "put",
                    "--url",
                    url,
                    "--body",
                    "@" + str(directory / "archive-off-request.private.json"),
                ],
            )
        state = az("stopped-readback", ["rest", "--method", "get", "--url", url], absent_ok=True)
        if state is not None and any(r.get("enabled") for r in state["properties"]["logs"]):
            raise RuntimeError("archive_export_stop_not_verified")
        return True

    if args.stop:
        print(json.dumps({"temporary_archive_export_stopped": stop(), "resources_deleted": 0}))
        return 0
    acceptance = json.loads(
        (ROOT / "docs/evidence/graph-archive-diagnostic-acceptance.json").read_text()
    )
    proposal_hash = hashlib.sha256(
        (ROOT / "docs/graph-route-isolation-proposal.md").read_bytes().replace(b"\r\n", b"\n")
    ).hexdigest()
    if not acceptance.get("accepted") or acceptance.get("proposal_sha256") != proposal_hash:
        raise RuntimeError("matching_archive_scope_acceptance_required")
    original_storage = az(
        "baseline-storage",
        [
            "storage",
            "account",
            "show",
            "--resource-group",
            "kb-agentdemo",
            "--name",
            config["azure_access"]["storageName"],
        ],
    )
    addresses = [
        r["ipAddressOrRange"]
        for r in original_storage["networkRuleSet"]["ipRules"]
        if r.get("action") == "Allow"
    ]
    if len(addresses) != 1:
        raise RuntimeError("one_existing_operator_ipv4_rule_required")
    address = ipaddress.ip_address(addresses[0])
    if address.version != 4 or not address.is_global:
        raise RuntimeError("global_single_operator_ipv4_required")
    operator = az(
        "operator",
        ["rest", "--method", "get", "--url", "https://graph.microsoft.com/v1.0/me?$select=id"],
    )
    if operator["id"] != config["operator_id"]:
        raise RuntimeError("designated_archive_operator_required")
    role = az("reader-role", ["role", "definition", "list", "--name", "Storage Blob Data Reader"])
    if len(role) != 1:
        raise RuntimeError("exact_blob_reader_role_required")
    parameters = directory / "archive.parameters.private.json"
    parameters.write_text(
        json.dumps(
            {
                "parameters": {
                    k: {"value": v}
                    for k, v in {
                        "enableProvisioning": True,
                        "operatorIpv4": str(address),
                        "operatorPrincipalId": operator["id"],
                        "blobReaderRoleId": role[0]["id"],
                    }.items()
                }
            }
        )
    )
    common = [
        "--resource-group",
        "kb-agentdemo",
        "--name",
        "agenttrace-graph-archive-diagnostic",
        "--template-file",
        str(ROOT / "work/infra/graph-archive-diagnostic.json"),
        "--parameters",
        "@" + str(parameters),
    ]
    inventory = az("inventory", ["resource", "list", "--resource-group", "kb-agentdemo"])
    preview = az("what-if", ["deployment", "group", "what-if", *common, "--no-pretty-print"])
    review_changes(preview, inventory, group)
    print(
        json.dumps(
            {
                "archive_plan_reviewed": True,
                "apply": args.apply,
                "raw_metadata_exception_accepted": True,
            }
        ),
        flush=True,
    )
    if not args.apply:
        return 0
    deployment = az(
        "deployment", ["deployment", "group", "create", *common, "--mode", "Incremental"]
    )
    outputs = deployment["properties"]["outputs"]
    account_id = outputs["storageAccountId"]["value"]
    account_name = outputs["storageAccountName"]["value"]
    account = az("account", ["storage", "account", "show", "--ids", account_id])
    firewall = account["networkRuleSet"]
    controls = (
        account["location"] == "eastus"
        and account["sku"]["name"] == "Standard_LRS"
        and account.get("tags", {}).get("purpose") == "owner-approved-raw-graph-diagnostic"
        and account["enableHttpsTrafficOnly"]
        and account["minimumTlsVersion"] == "TLS1_2"
        and account["allowBlobPublicAccess"] is False
        and account["allowSharedKeyAccess"] is False
        and firewall["defaultAction"] == "Deny"
        and firewall["bypass"] == "AzureServices"
        and [r["ipAddressOrRange"] for r in firewall["ipRules"]] == [str(address)]
    )
    grants = az(
        "reader-grants",
        [
            "role",
            "assignment",
            "list",
            "--scope",
            account_id + "/blobServices/default/containers/" + CONTAINER,
        ],
    )
    controls = controls and any(
        g["principalId"] == operator["id"]
        and g["roleDefinitionId"].lower() == role[0]["id"].lower()
        and g["scope"].lower()
        == (account_id + "/blobServices/default/containers/" + CONTAINER).lower()
        for g in grants
    )
    expiry = az(
        "expiry",
        [
            "storage",
            "account",
            "management-policy",
            "show",
            "--account-name",
            account_name,
            "--resource-group",
            "kb-agentdemo",
        ],
    )
    rules = expiry["policy"]["rules"]
    controls = (
        controls
        and len(rules) == 1
        and rules[0]["enabled"]
        and rules[0]["definition"]["actions"]["baseBlob"]["delete"][
            "daysAfterModificationGreaterThan"
        ]
        == 7
    )
    service = az(
        "blob-service",
        [
            "storage",
            "account",
            "blob-service-properties",
            "show",
            "--account-name",
            account_name,
            "--resource-group",
            "kb-agentdemo",
        ],
    )
    controls = (
        controls
        and not service.get("isVersioningEnabled")
        and not service["deleteRetentionPolicy"]["enabled"]
        and not service["containerDeleteRetentionPolicy"]["enabled"]
    )
    if not controls:
        raise RuntimeError("archive_controls_not_verified_export_not_enabled")
    list_url = "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings?api-version=2017-04-01"
    before = az("settings-before", ["rest", "--method", "get", "--url", list_url])
    if any(
        v["name"] == SETTING and any(r.get("enabled") for r in v["properties"]["logs"])
        for v in before["value"]
    ):
        raise RuntimeError("archive_route_already_active_operator_review_required")
    for state in [False, True]:
        path = directory / (
            "archive-on-request.private.json" if state else "archive-off-request.private.json"
        )
        path.write_text(
            json.dumps(
                {
                    "properties": {
                        "storageAccountId": account_id,
                        "logs": [
                            {
                                "category": CATEGORY,
                                "enabled": state,
                                "retentionPolicy": {"enabled": False, "days": 0},
                            }
                        ],
                    }
                }
            )
        )
    start = datetime.now(UTC)
    report = {
        "executed_at": start.isoformat(),
        "scope_acceptance_recorded": True,
        "storage_controls_verified": True,
        "archive_route_enabled": False,
        "exact_control_request_ids_observed": 0,
        "bounded_objects_examined": 0,
        "archive_source_delivery_proven": False,
        "email_mutations": 0,
    }
    try:
        az(
            "enabled",
            [
                "rest",
                "--method",
                "put",
                "--url",
                url,
                "--body",
                "@" + str(directory / "archive-on-request.private.json"),
            ],
        )
        current = az("enabled-readback", ["rest", "--method", "get", "--url", url])
        active = [r["category"] for r in current["properties"]["logs"] if r.get("enabled")]
        if (
            active != [CATEGORY]
            or current["properties"]["storageAccountId"].lower() != account_id.lower()
        ):
            raise RuntimeError("archive_route_enable_not_confirmed")
        report["archive_route_enabled"] = True
        probe = subprocess.run(
            [sys.executable, str(ROOT / "scripts/probe-graph-activity.py")],
            capture_output=True,
            timeout=120,
        )
        if probe.returncode:
            raise RuntimeError("archive_read_only_controls_failed")
        controls = json.loads((directory / "read-only-probes.private.json").read_text())
        expected_ids = {
            str(p[k]).lower()
            for p in controls
            for k in ["request_id", "client_request_id"]
            if p.get(k)
        }
        deadline = time.monotonic() + args.wait_seconds
        seen = set()
        examined = set()
        while True:
            blobs = az(
                "blob-list",
                [
                    "storage",
                    "blob",
                    "list",
                    "--account-name",
                    account_name,
                    "--container-name",
                    CONTAINER,
                    "--auth-mode",
                    "login",
                    "--num-results",
                    "5",
                ],
            )
            for index, blob in enumerate(blobs):
                modified = datetime.fromisoformat(
                    blob["properties"]["lastModified"].replace("Z", "+00:00")
                )
                if datetime.now(UTC) - modified > timedelta(days=7):
                    continue
                if not 0 < blob["properties"]["contentLength"] <= 4 * 1024 * 1024:
                    continue
                capture = directory / ("archive-object-" + str(index) + ".private.json")
                az(
                    "blob-download",
                    [
                        "storage",
                        "blob",
                        "download",
                        "--account-name",
                        account_name,
                        "--container-name",
                        CONTAINER,
                        "--name",
                        blob["name"],
                        "--file",
                        str(capture),
                        "--auth-mode",
                        "login",
                        "--overwrite",
                        "true",
                        "--no-progress",
                    ],
                )
                payload = json.loads(capture.read_text(encoding="utf-8-sig"))

                def visit(value):
                    if isinstance(value, dict):
                        for key, item in value.items():
                            if (
                                key.lower() in {"requestid", "clientrequestid", "operationid"}
                                and isinstance(item, str)
                                and item.lower() in expected_ids
                            ):
                                seen.add(item.lower())
                            visit(item)
                    elif isinstance(value, list):
                        for item in value:
                            visit(item)

                visit(payload)
                examined.add(blob["name"])
            report["exact_control_request_ids_observed"] = len(seen)
            report["bounded_objects_examined"] = len(examined)
            report["archive_source_delivery_proven"] = bool(seen)
            print(
                json.dumps(
                    {"archive_objects_examined": len(examined), "exact_control_ids_seen": len(seen)}
                ),
                flush=True,
            )
            if seen or time.monotonic() >= deadline:
                break
            time.sleep(min(30, max(1, deadline - time.monotonic())))
    except Exception as error:
        report["test_error"] = type(error).__name__
        raise
    finally:
        try:
            report["temporary_archive_export_stopped"] = stop()
            after = az("settings-after", ["rest", "--method", "get", "--url", list_url])
            report["other_tenant_settings_preserved"] = {
                v["name"]: v for v in before["value"] if v["name"] != SETTING
            } == {v["name"]: v for v in after["value"] if v["name"] != SETTING}
        finally:
            report["completed_at"] = datetime.now(UTC).isoformat()
            (ROOT / "docs/evidence/graph-archive-diagnostic-validation.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
            print(json.dumps(report), flush=True)
    return 0 if report["archive_source_delivery_proven"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
