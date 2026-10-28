"""Review/apply the accepted, dedicated Graph notification metadata transport."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from deployment_review import review_changes

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    private = ROOT / "work/private/secure-access"
    output = ROOT / "work/private/mail-ingestion"
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((private / "sandbox-settings.private.json").read_text(encoding="utf-8-sig"))
    identities = json.loads((private / "workload-identities.private.json").read_text())

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
        (output / (label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (output / (label + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError(
                "notification_transport_configuration_failed_see_private_diagnostics"
            )
        try:
            return json.loads(result.stdout.decode("utf-8")) if result.stdout.strip() else {}
        except UnicodeDecodeError:
            return json.loads(result.stdout.decode("cp1252"))

    inventory = az("transport-inventory", ["resource", "list", "-g", "kb-agentdemo"])
    if any(
        r["type"].lower() == "microsoft.eventgrid/partnerconfigurations"
        and r.get("tags", {}).get("project") != "AgentTrace"
        for r in inventory
    ):
        raise RuntimeError("existing_shared_partner_configuration_requires_preserving_owner_review")
    partners = az("verified-partners", ["eventgrid", "partner", "verified-partner", "list"])
    graph = [p for p in partners if "microsoftgraph" in json.dumps(p).lower().replace(" ", "")]
    if len(graph) != 1:
        raise RuntimeError("unique_verified_microsoft_graph_partner_required")
    registration = graph[0].get("partnerRegistrationImmutableId") or graph[0].get(
        "properties", {}
    ).get("partnerRegistrationImmutableId")
    if not registration:
        raise RuntimeError("verified_partner_registration_missing")
    role_ids = {}
    for key, name in {
        "queueContributorRoleId": "Storage Queue Data Contributor",
        "queueProcessorRoleId": "Storage Queue Data Message Processor",
        "blobContributorRoleId": "Storage Blob Data Contributor",
    }.items():
        roles = az(key, ["role", "definition", "list", "--name", name])
        if len(roles) != 1:
            raise RuntimeError("exact_builtin_role_required")
        role_ids[key] = roles[0]["id"]
    values = {
        "enableProvisioning": True,
        "operatorIpv4": config["operator_ipv4"],
        "operatorPrincipalId": config["operator_id"],
        "collectorPrincipalId": identities["mail-collector"]["service_principal"]["id"],
        "graphPartnerRegistrationId": registration,
        "partnerAuthorizationExpiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        **role_ids,
    }
    params = output / "transport.parameters.private.json"
    params.write_text(
        json.dumps({"parameters": {k: {"value": v} for k, v in values.items()}}, indent=2)
    )
    template = ROOT / "work/infra/notification-transport.json"
    if not template.exists():
        raise RuntimeError("compile_notification_bicep_first")
    common = [
        "--resource-group",
        "kb-agentdemo",
        "--name",
        "agenttrace-notification-transport",
        "--template-file",
        str(template),
        "--parameters",
        "@" + str(params),
    ]
    preview = az(
        "transport-what-if", ["deployment", "group", "what-if", *common, "--no-pretty-print"], 300
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
                "changes": {
                    v: sum(c["changeType"] == v for c in preview["changes"])
                    for v in sorted({c["changeType"] for c in preview["changes"]})
                },
                "applied": args.apply,
            }
        ),
        flush=True,
    )
    if args.apply:
        result = az(
            "transport-deployment",
            ["deployment", "group", "create", *common, "--mode", "Incremental"],
            600,
        )
        settings = {k: v["value"] for k, v in result["properties"]["outputs"].items()}
        settings.update(
            {
                "partner_topic_name": "agenttrace-synthetic-mail",
                "subscription": config["subscription"],
            }
        )
        (output / "transport-settings.private.json").write_text(json.dumps(settings, indent=2))


if __name__ == "__main__":
    main()
