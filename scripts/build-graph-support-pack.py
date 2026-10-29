"""Prepare an operator-private support note; do not contact or upload to Microsoft."""

import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "work/private/graph-activity"
    settings = json.loads((directory / "logging-settings.private.json").read_text())
    evidence = {}
    for name in [
        "graph-activity-diagnostics",
        "graph-route-canary-validation",
        "graph-route-refresh-validation",
        "graph-archive-diagnostic-validation",
        "agent-audit-fallback-validation",
    ]:
        path = ROOT / "docs/evidence" / (name + ".json")
        if path.exists():
            evidence[name] = json.loads(path.read_text())
    probes = []
    for name in ["read-only-probes", "earlier-read-only-probes", "directory-control-probes"]:
        path = directory / (name + ".private.json")
        if path.exists():
            probes.extend(json.loads(path.read_text()))
    probes.sort(key=lambda value: value["time"])
    context = {
        key: settings.get(key)
        for key in [
            "tenant_id",
            "workspaceResourceId",
            "workspaceCustomerId",
            "transformationRuleId",
            "diagnostic_setting_name",
            "enabled_at",
            "last_route_refresh_attempt_at",
            "last_route_refresh_at",
            "clients",
            "collector_clients",
        ]
    }
    archive_deployment = directory / "archive-deployment.private.json"
    if archive_deployment.is_file():
        deployment = json.loads(archive_deployment.read_text())
        context["isolated_archive_account_id"] = deployment["properties"]["outputs"][
            "storageAccountId"
        ]["value"]
    references = [
        {
            key: probe.get(key)
            for key in [
                "label",
                "time",
                "request_id",
                "client_request_id",
                "client_id",
                "http_status",
                "expected_logged",
            ]
        }
        for probe in probes[-16:]
    ]
    text = (
        "# Private Graph activity delivery support note\n\n"
        + "Prepared UTC: "
        + datetime.now(UTC).isoformat()
        + "\n\n"
        + "This note has not been submitted. Review before sharing through an approved Microsoft support channel. "
        + "It contains tenant/resource/application/request identifiers, but no access token, credential, certificate, email body or customer message.\n\n"
        + "## Request\n\nPlease verify MicrosoftGraphActivityLogs category provisioning and resource-tenant export routing for this tenant. "
        + "Confirmed read-only Microsoft Graph requests have not produced visible matching records in the configured destination. "
        + "The destination's independent synthetic Logs Ingestion API canary was ingested and queried successfully. "
        + "That canary does not prove the Graph publisher, the Graph-specific transformation or its query authorization. "
        + "DCR telemetry currently has no measurement samples, rather than measured zero inputs. "
        + "A single dedicated-route refresh was performed and restored, with the brief unknown-loss interval recorded. "
        + "Please check category activation, delivery failures and table access/protection behavior. "
        + "The separately approved native Blob diagnostic observed no objects in its ten-minute foreground test and was then stopped; "
        + "that result is inconclusive and does not prove native writer authentication compatibility or a tenant emission fault. "
        + "Please verify archive authorization under disabled shared-key access without changing it automatically. "
        + "The documented initial three-day activation window has not necessarily elapsed; please confirm whether provisioning is healthy. "
        + "Do not change Conditional Access, purchase licenses, broaden mailbox access or enable other tenant log categories.\n\n"
        + "## Context\n\n```json\n"
        + json.dumps(context, indent=2)
        + "\n```\n\n"
        + "## Executed diagnostics\n\n```json\n"
        + json.dumps(evidence, indent=2)
        + "\n```\n\n"
        + "## Exact read-only request references\n\n```json\n"
        + json.dumps(references, indent=2)
        + "\n```\n\n"
        + "## Available private captures\n\nThe operator has managed-resource/settings readbacks, license/tenant checks, the deployed transformation, "
        + "metric responses and exact request receipts in the protected graph-activity directory. Share only individually reviewed captures; "
        + "do not upload the whole private directory. Raw diagnostic captures follow the seven-day evidence policy.\n"
    )
    (directory / "support-request.private.md").write_text(text, encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {
                "private_support_note_prepared": True,
                "request_references": len(references),
                "submitted_to_microsoft": False,
            }
        )
    )


if __name__ == "__main__":
    main()
