"""Plan/apply only the accepted, firewall-restricted synthetic access resources."""

from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

from deployment_review import review_changes

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]


def configure(config_path: Path, apply: bool) -> None:
    if not config_path.resolve().is_relative_to((ROOT / "work/private").resolve()):
        raise ValueError("private_configuration_required")
    directory = config_path.resolve().parent
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    identities = json.loads((directory / "workload-identities.private.json").read_text())
    if config["resource_group"] != "kb-agentdemo" or config["region"] != "eastus":
        raise ValueError("unapproved_deployment_target")

    def az(label: str, args: list[str], timeout: int = 120) -> dict | list:
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                *args,
                "--subscription",
                config["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        (directory / (label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / (label + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError("azure_access_configuration_failed_see_private_diagnostic")
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except UnicodeDecodeError:
            return json.loads(result.stdout.decode("cp1252"))

    inventory = az(
        "azure-access-inventory", ["resource", "list", "--resource-group", "kb-agentdemo"]
    )
    workspace = next(
        r
        for r in inventory
        if r["type"].lower() == "microsoft.operationalinsights/workspaces"
        and r["location"] == "eastus"
    )
    with urlopen("https://api4.ipify.org?format=json", timeout=20) as response:
        operator_ip = str(ipaddress.IPv4Address(json.load(response)["ip"]))
    roles = {}
    for alias, name in {
        "queueSender": "Storage Queue Data Message Sender",
        "queueProcessor": "Storage Queue Data Message Processor",
        "blobContributor": "Storage Blob Data Contributor",
        "blobReader": "Storage Blob Data Reader",
        "cryptoOfficer": "Key Vault Crypto Officer",
    }.items():
        found = az("role-" + alias, ["role", "definition", "list", "--name", name])
        if len(found) != 1 or found[0]["roleName"] != name:
            raise RuntimeError("unambiguous_builtin_role_required")
        roles[alias] = found[0]["id"]
    parameters = {
        "enableProvisioning": True,
        "operatorIpv4": operator_ip,
        "operatorPrincipalId": config["operator_id"],
        "roleIds": roles,
        "collectorPrincipalId": identities["mail-collector"]["service_principal"]["id"],
        "auditPrincipalId": identities["audit-collector"]["service_principal"]["id"],
        "attributionPrincipalId": identities["attribution"]["service_principal"]["id"],
        "contentPrincipalId": identities["content"]["service_principal"]["id"],
        "apiPrincipalId": identities["api"]["service_principal"]["id"],
        "logWorkspaceId": workspace["id"],
        "signingKeyExpiry": int((datetime.now(UTC) + timedelta(days=90)).timestamp()),
    }
    param_path = directory / "azure-access.parameters.private.json"
    param_path.write_text(
        json.dumps({"parameters": {k: {"value": v} for k, v in parameters.items()}}, indent=2),
        encoding="utf-8",
    )
    template = ROOT / "work/infra/access-sandbox.json"
    if not template.is_file():
        raise RuntimeError("compile_infrastructure_before_plan_or_apply")
    common = [
        "--resource-group",
        "kb-agentdemo",
        "--name",
        "agenttrace-secure-access",
        "--template-file",
        str(template),
        "--parameters",
        "@" + str(param_path),
    ]
    preview = az(
        "azure-access-what-if",
        ["deployment", "group", "what-if", *common, "--no-pretty-print"],
        timeout=300,
    )
    changes = preview.get("changes", [])
    group_id = "/subscriptions/" + config["subscription"] + "/resourceGroups/kb-agentdemo"
    review_changes(preview, inventory, group_id)
    summary = {
        kind: sum(c["changeType"] == kind for c in changes)
        for kind in sorted({c["changeType"] for c in changes})
    }
    print(
        json.dumps(
            {
                "mode": "apply" if apply else "plan",
                "what_if_changes": summary,
                "region": "eastus",
                "compute_or_gpu_created": False,
            }
        ),
        flush=True,
    )
    if apply:
        deployment = az(
            "azure-access-deployment",
            ["deployment", "group", "create", *common, "--mode", "Incremental"],
            timeout=600,
        )
        outputs = {
            name: value["value"] for name, value in deployment["properties"]["outputs"].items()
        }
        # ARM's key-management service originates outside the operator firewall.
        # Bootstrap through the authenticated operator data plane; never enable a bypass.
        existing_keys = az(
            "signing-key-inventory",
            ["keyvault", "key", "list", "--vault-name", outputs["vaultName"]],
        )
        if not any(key["name"] == "evidence-signing" for key in existing_keys):
            az(
                "signing-key-bootstrap",
                [
                    "keyvault",
                    "key",
                    "create",
                    "--vault-name",
                    outputs["vaultName"],
                    "--name",
                    "evidence-signing",
                    "--kty",
                    "RSA",
                    "--size",
                    "2048",
                    "--ops",
                    "sign",
                    "verify",
                    "--expires",
                    datetime.fromtimestamp(parameters["signingKeyExpiry"], UTC).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                ],
            )
        parameters["assignKeyRoles"] = True
        param_path.write_text(
            json.dumps({"parameters": {k: {"value": v} for k, v in parameters.items()}}, indent=2),
            encoding="utf-8",
        )
        key_preview = az(
            "azure-key-roles-what-if",
            ["deployment", "group", "what-if", *common, "--no-pretty-print"],
            timeout=300,
        )
        review_changes(key_preview, inventory, group_id)
        az(
            "azure-key-roles-deployment",
            ["deployment", "group", "create", *common, "--mode", "Incremental"],
            timeout=600,
        )
        config.update({"azure_access": outputs, "operator_ipv4": operator_ip})
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {"deployment": "succeeded", "workload_data_plane_tests_still_required": True}
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    configure(arguments.config, arguments.apply)
