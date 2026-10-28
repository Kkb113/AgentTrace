"""Collect sanitized live-source evidence without publishing identifiers or bodies."""

import json
import subprocess
from pathlib import Path
from urllib.parse import unquote

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_ingestion.runtime import load

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "work/private/mail-ingestion"
    settings = json.loads((directory / "transport-settings.private.json").read_text())
    _, enrollment, store, pipeline, provider = load(directory / "runtime.private.json")
    baseline = json.loads(
        (ROOT / "work/private/secure-access/sandbox-settings.private.json").read_text(
            encoding="utf-8-sig"
        )
    )

    def az(label, commands):
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                *commands,
                "--subscription",
                settings["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=120,
        )
        (directory / (label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / (label + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError("live_ingestion_verification_request_failed")
        return json.loads(result.stdout)

    group = "/subscriptions/" + settings["subscription"] + "/resourceGroups/kb-agentdemo"
    topic_id = (
        group + "/providers/Microsoft.EventGrid/partnerTopics/" + settings["partner_topic_name"]
    )
    topic = az("live-topic", ["resource", "show", "--ids", topic_id, "--api-version", "2022-06-15"])
    delivery = az(
        "live-delivery",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com"
            + topic_id
            + "/eventSubscriptions/agenttrace-durable-mail-ingestion?api-version=2025-02-15",
        ],
    )["properties"]
    storage = az(
        "live-notification-storage",
        [
            "storage",
            "account",
            "show",
            "--resource-group",
            "kb-agentdemo",
            "--name",
            settings["storageAccountName"],
        ],
    )
    original = az(
        "live-original-storage",
        [
            "storage",
            "account",
            "show",
            "--resource-group",
            "kb-agentdemo",
            "--name",
            baseline["azure_access"]["storageName"],
        ],
    )
    vault = az(
        "live-original-vault",
        [
            "keyvault",
            "show",
            "--resource-group",
            "kb-agentdemo",
            "--name",
            baseline["azure_access"]["vaultName"],
        ],
    )
    with store.database.connect() as connection:
        copies = connection.execute(
            "SELECT message_ref,locator_cipher,current_version FROM ingest_copies WHERE source_ref=%s",
            (enrollment.source_ref,),
        ).fetchall()
        notifications = connection.execute(
            "SELECT event_ref,locator_cipher,state FROM ingest_events WHERE source_ref=%s",
            (enrollment.source_ref,),
        ).fetchall()
        audit = connection.execute("SELECT count(*) AS n FROM ingest_audit_events").fetchone()
    native = [
        r
        for r in notifications
        if store.cipher.open(bytes(r["locator_cipher"]), context="event:" + str(r["event_ref"]))[
            "subscription_ref"
        ]
        != "delta-reconciliation"
    ]
    subscriptions = store.subscriptions(enrollment.source_ref)
    native_config = [
        pipeline.mailbox.transport.request(
            "GET", "https://graph.microsoft.com/v1.0/subscriptions/" + s["id"]
        )
        for s in subscriptions
        if s["state"] == "active"
    ]
    checks = {
        "live_graph_subscription_metadata_only": bool(native_config)
        and all(s.get("includeResourceData") is False for s in native_config),
        "graph_subscription_folder_scope": bool(native_config)
        and all(
            str(enrollment.mailbox_id) in unquote(s["resource"])
            and any(folder in unquote(s["resource"]) for folder in enrollment.folder_ids)
            for s in native_config
        ),
        "graph_subscription_validation_secret_matches": bool(native_config)
        and all(
            s.get("clientState") == enrollment.client_state.get_secret_value()
            for s in native_config
        ),
        "partner_topic_activated": topic["properties"]["activationState"] == "Activated",
        "managed_identity_cloud_event_delivery": delivery.get("deliveryWithResourceIdentity", {})
        .get("identity", {})
        .get("type")
        == "SystemAssigned"
        and delivery["eventDeliverySchema"] == "CloudEventSchemaV1_0",
        "native_notification_received_and_processed": bool(native)
        and all(n["state"] == "processed" for n in native),
        "synthetic_inventory_reconciled": len(copies) >= 4
        and all(c["current_version"] for c in copies),
        "exact_synthetic_exchange_audit_ingested": audit["n"] >= 3,
        "dedicated_storage_standard_lrs": storage["sku"]["name"] == "Standard_LRS"
        and storage["location"] == "eastus",
        "dedicated_storage_no_shared_keys": storage["allowSharedKeyAccess"] is False,
        "accepted_notification_network_exception_only": storage["networkRuleSet"]["defaultAction"]
        == "Deny"
        and storage["networkRuleSet"]["bypass"] == "AzureServices",
        "original_evidence_firewall_unchanged": original["networkRuleSet"]["bypass"] == "None"
        and original["networkRuleSet"]["defaultAction"] == "Deny",
        "original_vault_firewall_unchanged": vault["properties"]["networkAcls"]["bypass"] == "None"
        and vault["properties"]["networkAcls"]["defaultAction"] == "Deny",
    }
    result = {
        "kind": "actual_live_calls",
        "checks": checks,
        "all_passed": all(checks.values()),
        "observed_message_copies": len(copies),
        "native_notifications": len(native),
        "exchange_audit_records": audit["n"],
        "email_write_actions": 0,
        "raw_snapshots_enabled": False,
        "graph_activity_source": "not_configured",
        "office_audit_source": "graph_exchange_audit_query",
        "content_scorer": "not_installed",
    }
    target = ROOT / "docs/evidence/mail-ingestion-live-validation.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
