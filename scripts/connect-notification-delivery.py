"""Activate only AgentTrace's Graph-created partner topic and scoped MI delivery."""

import json
import subprocess
import time
from pathlib import Path

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "work/private/mail-ingestion"
    settings = json.loads((directory / "transport-settings.private.json").read_text())
    subscription = settings["subscription"]
    group = "/subscriptions/" + subscription + "/resourceGroups/kb-agentdemo"
    topic_id = (
        group + "/providers/Microsoft.EventGrid/partnerTopics/" + settings["partner_topic_name"]
    )

    def az(label, commands, *, allow_pending=False):
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                *commands,
                "--subscription",
                subscription,
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=180,
        )
        (directory / (label + ".private.json")).write_bytes(result.stdout)
        if result.returncode:
            (directory / (label + ".error.private.txt")).write_bytes(result.stderr)
            if allow_pending and b"ResourceNotFound" in result.stderr:
                return None
            raise RuntimeError("notification_delivery_configuration_failed_see_private_diagnostics")
        return json.loads(result.stdout) if result.stdout.strip() else {}

    topic = az(
        "partner-topic-before",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com" + topic_id + "?api-version=2022-06-15",
        ],
    )
    if topic["location"].lower() != "eastus" or topic["name"] != "agenttrace-synthetic-mail":
        raise RuntimeError("unexpected_graph_created_partner_topic")
    patch = directory / "partner-identity-patch.private.json"
    patch.write_text(
        json.dumps(
            {
                "identity": {"type": "SystemAssigned"},
                "tags": {
                    **(topic.get("tags") or {}),
                    "project": "AgentTrace",
                    "purpose": "synthetic-notification-metadata",
                },
            }
        )
    )
    updated = az(
        "partner-topic-identity",
        [
            "rest",
            "--method",
            "patch",
            "--url",
            "https://management.azure.com" + topic_id + "?api-version=2022-06-15",
            "--body",
            "@" + str(patch),
        ],
    )
    principal = updated["identity"]["principalId"]
    for label, role, scope in [
        (
            "delivery-queue-role",
            "Storage Queue Data Message Sender",
            settings["queueResourceId"].split("/queueServices/")[0],
        ),
        (
            "delivery-deadletter-role",
            "Storage Blob Data Contributor",
            settings["deadLetterResourceId"].split("/blobServices/")[0],
        ),
    ]:
        if not (scope.lower() + "/").startswith(
            group.lower()
            + "/providers/microsoft.storage/storageaccounts/"
            + settings["storageAccountName"].lower()
            + "/"
        ):
            raise RuntimeError("delivery_role_scope_out_of_bounds")
        az(
            label,
            [
                "role",
                "assignment",
                "create",
                "--assignee-object-id",
                principal,
                "--assignee-principal-type",
                "ServicePrincipal",
                "--role",
                role,
                "--scope",
                scope,
            ],
        )
    if topic["properties"].get("activationState") != "Activated":
        az(
            "partner-topic-activation",
            [
                "eventgrid",
                "partner",
                "topic",
                "activate",
                "--resource-group",
                "kb-agentdemo",
                "--name",
                settings["partner_topic_name"],
            ],
        )
    storage_id = settings["queueResourceId"].split("/queueServices/")[0]
    delivery = directory / "native-event-subscription-body.private.json"
    delivery.write_text(
        json.dumps(
            {
                "properties": {
                    "deliveryWithResourceIdentity": {
                        "identity": {"type": "SystemAssigned"},
                        "destination": {
                            "endpointType": "StorageQueue",
                            "properties": {
                                "resourceId": storage_id,
                                "queueName": "mail-notifications",
                                "queueMessageTimeToLiveInSeconds": 604800,
                            },
                        },
                    },
                    "deadLetterWithResourceIdentity": {
                        "identity": {"type": "SystemAssigned"},
                        "deadLetterDestination": {
                            "endpointType": "StorageBlob",
                            "properties": {
                                "resourceId": storage_id,
                                "blobContainerName": "notification-deadletters",
                            },
                        },
                    },
                    "eventDeliverySchema": "CloudEventSchemaV1_0",
                    "retryPolicy": {"maxDeliveryAttempts": 30, "eventTimeToLiveInMinutes": 1440},
                    "labels": ["AgentTrace", "synthetic-only"],
                }
            }
        )
    )
    event_subscription = az(
        "native-event-subscription",
        [
            "rest",
            "--method",
            "put",
            "--url",
            "https://management.azure.com"
            + topic_id
            + "/eventSubscriptions/agenttrace-durable-mail-ingestion?api-version=2025-02-15",
            "--body",
            "@" + str(delivery),
        ],
    )
    print(
        json.dumps(
            {
                "partner_topic_activated": True,
                "managed_identity_delivery_requested": True,
                "delivery_schema": event_subscription.get("properties", {}).get(
                    "eventDeliverySchema"
                ),
                "queue_ttl_seconds": 604800,
                "cloud_compute_created": False,
            }
        )
    )
    # ARM accepts this operation asynchronously. A Creating response is not success.
    for attempt in range(30):
        status = az(
            "native-event-subscription-terminal",
            [
                "rest",
                "--method",
                "get",
                "--url",
                "https://management.azure.com"
                + topic_id
                + "/eventSubscriptions/agenttrace-durable-mail-ingestion?api-version=2025-02-15",
            ],
            allow_pending=True,
        )
        state = status.get("properties", {}).get("provisioningState") if status else None
        if state == "Succeeded":
            print(
                json.dumps(
                    {
                        "native_delivery_terminal_state": "Succeeded",
                        "managed_identity_delivery_confirmed": True,
                    }
                )
            )
            break
        if state in {"Failed", "Canceled"}:
            raise RuntimeError("native_delivery_terminal_provisioning_failed")
        time.sleep(2)
    else:
        raise RuntimeError("native_delivery_terminal_state_unconfirmed")


if __name__ == "__main__":
    main()
