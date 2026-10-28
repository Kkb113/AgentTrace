"""Effective, bounded synthetic permission probes; no mail mutation is attempted.

All credentials remain in memory. Raw source responses and real identifiers stay in
the supplied ignored private directory. Only reviewed boolean/status evidence is
written to work/reports for a separate publication review.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener, urlopen
from uuid import NAMESPACE_URL, uuid4, uuid5

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_foundation.access_policy import EvidenceCapability, MailboxReadPolicy
from agenttrace_foundation.authorization import AuthorizationPolicy, EntraTokenValidator
from agenttrace_foundation.mail_reader import NoRedirect, ReadOnlyMailReader
from agenttrace_foundation.workload_identity import CertificateTokenProvider

ROOT = Path(__file__).resolve().parents[1]


def verify(config_path: Path, section: str) -> int:
    directory = config_path.resolve().parent
    if not directory.is_relative_to((ROOT / "work/private").resolve()):
        raise ValueError("ignored_private_configuration_required")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    identities = json.loads((directory / "workload-identities.private.json").read_text())
    cases = []
    providers = {}
    captured = {}

    def record(name: str, actual: object, expected: object) -> None:
        case = {"name": name, "expected": expected, "actual": actual, "passed": actual == expected}
        cases.append(case)
        print(json.dumps(case), flush=True)

    def token(alias: str, resource: str) -> str:
        if alias not in providers:
            item = identities[alias]
            providers[alias] = CertificateTokenProvider(
                config["tenant"],
                item["application"]["appId"],
                item["certificate"]["thumbprint"],
                ROOT / "scripts/manage-workload-certificate.ps1",
            )
        return providers[alias].token(resource)

    def request(
        name: str,
        alias: str,
        resource: str,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: dict | None = None,
    ) -> tuple[int, bytes]:
        supplied = {"Authorization": "Bearer " + token(alias, resource), **(headers or {})}
        if resource == "https://storage.azure.com":
            supplied.update(
                {
                    "x-ms-version": "2023-11-03",
                    "x-ms-date": format_datetime(datetime.now(UTC), usegmt=True),
                }
            )
        try:
            with build_opener(NoRedirect()).open(
                Request(url, data=body, method=method, headers=supplied), timeout=30
            ) as response:
                status, source = response.status, response.read(1_048_576)
        except HTTPError as error:
            status, source = error.code, error.read(1_048_576)
        (directory / (name + ".response.private")).write_bytes(source)
        return status, source

    def admin_get(name: str, path: str, origin: str = "https://graph.microsoft.com/v1.0/") -> dict:
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                "rest",
                "--method",
                "GET",
                "--url",
                origin + path,
                "--subscription",
                config["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            check=False,
            timeout=90,
        )
        if result.returncode:
            (directory / (name + ".error.private.txt")).write_bytes(result.stderr)
            raise RuntimeError("administrator_inventory_unavailable")
        (directory / (name + ".response.private")).write_bytes(result.stdout)
        try:
            return json.loads(result.stdout.decode("utf-8"))
        except UnicodeDecodeError:
            return json.loads(result.stdout.decode("cp1252"))

    if section in {"all", "mailbox"}:
        control = admin_get(
            "control-account",
            "users/" + config["control_mailbox_id"] + "?$select=id,accountEnabled,mail",
        )
        record(
            "negative_control_exists_and_sign_in_is_disabled",
            control.get("id") == config["control_mailbox_id"]
            and control.get("accountEnabled") is False
            and bool(control.get("mail")),
            True,
        )
        query = urlencode(
            {
                "$top": "10",
                "$select": "id,changeKey,subject,sentDateTime,internetMessageId",
                "$filter": "startswith(subject,'AgentTrace synthetic test:')",
            }
        )
        status, source = request(
            "allowed-mailbox",
            "mail-collector",
            "https://graph.microsoft.com",
            "GET",
            "https://graph.microsoft.com/v1.0/users/" + config["mailbox_id"] + "/messages?" + query,
        )
        record("collector_reads_approved_mailbox", status, 200)
        if status == 200:
            message = next(
                item for item in json.loads(source)["value"] if "CLAUDE-01" in item["subject"]
            )
            captured.update(message)
            capability = EvidenceCapability(
                config["mailbox_id"],
                message["id"],
                message["changeKey"],
                datetime.now(UTC) + timedelta(hours=1),
            )
            body = ReadOnlyMailReader(
                MailboxReadPolicy(config["mailbox_id"], frozenset({message["id"]})),
                lambda: token("mail-collector", "https://graph.microsoft.com"),
            ).read_body(capability)
            record(
                "collector_reads_only_authorized_synthetic_body",
                "Synthetic test only." in body.text,
                True,
            )
        for alias, mailbox, name in [
            (
                "mail-collector",
                config["control_mailbox_id"],
                "collector_denied_out_of_scope_mailbox",
            ),
            ("content", config["mailbox_id"], "content_identity_denied_direct_mailbox"),
            ("attribution", config["mailbox_id"], "attribution_identity_denied_direct_mailbox"),
            ("audit-collector", config["mailbox_id"], "audit_identity_denied_mailbox_body_access"),
        ]:
            status, _ = request(
                name,
                alias,
                "https://graph.microsoft.com",
                "GET",
                f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages?$top=1&$select=id",
            )
            record(name, status, 403)
        graph_roles = admin_get(
            "graph-public-role-definitions",
            "servicePrincipals?$filter=appId eq '00000003-0000-0000-c000-000000000000'&$select=id,appRoles",
        )["value"][0]
        audit_role = next(
            r["id"]
            for r in graph_roles["appRoles"]
            if r["value"] == "AuditLogsQuery-Exchange.Read.All"
        )
        for alias, item in identities.items():
            grants = admin_get(
                "effective-grants-" + alias,
                "servicePrincipals/" + item["service_principal"]["id"] + "/appRoleAssignments",
            )["value"]
            actual = {(g["resourceId"], g["appRoleId"]) for g in grants}
            allowed = (
                {(graph_roles["id"], audit_role)}
                if alias == "audit-collector"
                else {
                    (
                        identities["api"]["service_principal"]["id"],
                        str(uuid5(NAMESPACE_URL, "agenttrace:api-role:Viewer")),
                    )
                }
                if alias == "access-test"
                else set()
            )
            record("effective_entra_grants_exact_" + alias, actual == allowed, True)
            delegated = admin_get(
                "delegated-grants-" + alias,
                "oauth2PermissionGrants?$filter=clientId eq '"
                + item["service_principal"]["id"]
                + "'",
            )["value"]
            record("no_hidden_delegated_grants_" + alias, len(delegated), 0)

    if section in {"all", "configuration"}:
        arm = "https://management.azure.com/"
        group = f"subscriptions/{config['subscription']}/resourceGroups/kb-agentdemo"
        storage_path = (
            group
            + "/providers/Microsoft.Storage/storageAccounts/"
            + config["azure_access"]["storageName"]
        )
        vault_path = (
            group + "/providers/Microsoft.KeyVault/vaults/" + config["azure_access"]["vaultName"]
        )
        storage = admin_get(
            "storage-effective-configuration", storage_path + "?api-version=2023-05-01", arm
        )
        properties = storage["properties"]
        network = properties["networkAcls"]
        record(
            "storage_effective_sku_region_and_oauth_boundary",
            storage["sku"]["name"] == "Standard_LRS"
            and storage["location"] == "eastus"
            and properties["allowSharedKeyAccess"] is False
            and properties["allowBlobPublicAccess"] is False
            and properties["minimumTlsVersion"] == "TLS1_2",
            True,
        )
        record(
            "storage_effective_exact_operator_ip_firewall",
            network["defaultAction"] == "Deny"
            and network["bypass"] == "None"
            and {rule["value"] for rule in network["ipRules"]} == {config["operator_ipv4"]}
            and not network.get("virtualNetworkRules"),
            True,
        )
        vault = admin_get(
            "vault-effective-configuration", vault_path + "?api-version=2023-07-01", arm
        )
        properties = vault["properties"]
        network = properties["networkAcls"]
        record(
            "vault_effective_standard_rbac_nonbypass_firewall",
            vault["location"] == "eastus"
            and properties["sku"]["name"].lower() == "standard"
            and properties["enableRbacAuthorization"] is True
            and properties["enablePurgeProtection"] is True
            and not properties["accessPolicies"]
            and network["defaultAction"] == "Deny"
            and network["bypass"] == "None"
            and {rule["value"] for rule in network["ipRules"]} == {config["operator_ipv4"] + "/32"},
            True,
        )
        lifecycle = admin_get(
            "raw-effective-lifecycle",
            storage_path + "/managementPolicies/default?api-version=2023-05-01",
            arm,
        )
        rule = lifecycle["properties"]["policy"]["rules"][0]
        record(
            "raw_evidence_has_effective_seven_day_lifecycle",
            rule["enabled"] is True
            and rule["definition"]["filters"]["prefixMatch"] == ["raw-evidence/"]
            and rule["definition"]["actions"]["baseBlob"]["delete"][
                "daysAfterModificationGreaterThan"
            ]
            == 7,
            True,
        )
        blob = admin_get(
            "raw-effective-blob-retention",
            storage_path + "/blobServices/default?api-version=2023-05-01",
            arm,
        )["properties"]
        record(
            "raw_blob_versioning_and_soft_delete_are_disabled",
            blob["isVersioningEnabled"] is False
            and blob["deleteRetentionPolicy"]["enabled"] is False
            and blob["containerDeleteRetentionPolicy"]["enabled"] is False,
            True,
        )
        inventory = json.loads((directory / "resource-inventory.private.json").read_text())
        workspace = next(
            r["id"]
            for r in inventory
            if r["type"].lower() == "microsoft.operationalinsights/workspaces"
            and r["location"] == "eastus"
        )
        for alias, path in [
            ("keys", vault_path),
            ("blobs", storage_path + "/blobServices/default"),
            ("queues", storage_path + "/queueServices/default"),
        ]:
            diagnostics = admin_get(
                "effective-access-diagnostics-" + alias,
                path
                + "/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview",
                arm,
            )["value"]
            target = next(
                item["properties"] for item in diagnostics if item["name"] == "AgentTraceAccess"
            )
            record(
                "resource_access_diagnostics_enabled_" + alias,
                target["workspaceId"].lower() == workspace.lower()
                and any(log["enabled"] for log in target["logs"]),
                True,
            )
        for alias, identity in identities.items():
            application = admin_get(
                "effective-certificate-policy-" + alias,
                "applications/"
                + identity["application"]["id"]
                + "?$select=id,passwordCredentials,keyCredentials",
            )
            record(
                "no_client_secret_and_one_bounded_certificate_" + alias,
                not application["passwordCredentials"]
                and len(application["keyCredentials"]) == 1
                and (
                    datetime.fromisoformat(
                        application["keyCredentials"][0]["endDateTime"].replace("Z", "+00:00")
                    )
                    - datetime.now(UTC)
                ).total_seconds()
                <= 90 * 86400,
                True,
            )
            directory_roles = admin_get(
                "effective-directory-roles-" + alias,
                "servicePrincipals/"
                + identity["service_principal"]["id"]
                + "/transitiveMemberOf/microsoft.graph.directoryRole?$select=id",
            )["value"]
            record("workload_has_no_directory_administrator_role_" + alias, len(directory_roles), 0)
        resource_root = "/" + group
        raw_scope = ("/" + storage_path + "/blobServices/default/containers/raw-evidence").lower()
        queue_scope = ("/" + storage_path + "/queueServices/default/queues/").lower()
        key_scope = ("/" + vault_path + "/keys/evidence-signing").lower()
        suffix = config["azure_access"]["vaultName"].removeprefix("agenttrace-")
        sender, processor = (
            "Storage Queue Data Message Sender",
            "Storage Queue Data Message Processor",
        )
        expected_roles = {
            "mail-collector": {
                (raw_scope, "Storage Blob Data Contributor"),
                (queue_scope + "agent-evidence", sender),
                (queue_scope + "content-analysis", sender),
            },
            "audit-collector": {
                (raw_scope, "Storage Blob Data Contributor"),
                (queue_scope + "agent-evidence", sender),
            },
            "attribution": {
                (raw_scope, "Storage Blob Data Reader"),
                (queue_scope + "agent-evidence", processor),
                (queue_scope + "agent-evidence-poison", sender),
                (key_scope, "AgentTrace Evidence Signer " + suffix),
            },
            "content": {
                (queue_scope + "content-analysis", processor),
                (queue_scope + "content-analysis-poison", sender),
            },
            "api": {(key_scope, "AgentTrace Evidence Verifier " + suffix)},
            "access-test": set(),
        }
        inspected = set()
        for alias, identity in identities.items():
            response = subprocess.run(
                [
                    *azure_cli_prefix(),
                    "role",
                    "assignment",
                    "list",
                    "--assignee-object-id",
                    identity["service_principal"]["id"],
                    "--all",
                    "--subscription",
                    config["subscription"],
                    "--only-show-errors",
                    "-o",
                    "json",
                ],
                capture_output=True,
                timeout=90,
                check=False,
            )
            (directory / ("effective-azure-roles-" + alias + ".response.private")).write_bytes(
                response.stdout
            )
            if response.returncode:
                raise RuntimeError("effective_azure_role_inventory_unavailable")
            roles = json.loads(response.stdout.decode("utf-8"))
            actual_roles = {(role["scope"].lower(), role["roleDefinitionName"]) for role in roles}
            record(
                "effective_azure_resource_roles_exact_" + alias,
                actual_roles == expected_roles[alias],
                True,
            )
            for assignment in roles:
                if (
                    assignment["roleDefinitionName"].startswith("AgentTrace Evidence ")
                    and assignment["roleDefinitionId"] not in inspected
                ):
                    inspected.add(assignment["roleDefinitionId"])
                    definition = admin_get(
                        "custom-role-" + alias,
                        assignment["roleDefinitionId"].lstrip("/") + "?api-version=2022-04-01",
                        arm,
                    )["properties"]
                    data_actions = {
                        value
                        for permission in definition["permissions"]
                        for value in permission.get("dataActions", [])
                    }
                    expected_actions = {
                        "Microsoft.KeyVault/vaults/keys/read",
                        "Microsoft.KeyVault/vaults/keys/verify/action",
                    }
                    if alias == "attribution":
                        expected_actions.add("Microsoft.KeyVault/vaults/keys/sign/action")
                    record(
                        "custom_key_role_has_only_required_crypto_actions_" + alias,
                        data_actions == expected_actions
                        and not any(
                            permission.get("actions") for permission in definition["permissions"]
                        )
                        and {scope.lower() for scope in definition["assignableScopes"]}
                        == {resource_root.lower()},
                        True,
                    )

    if section in {"all", "azure"}:
        azure = config["azure_access"]
        storage, vault = azure["storageName"], azure["vaultName"]
        blob = f"https://{storage}.blob.core.windows.net/raw-evidence/access-test/{uuid4().hex}.txt"
        fixture = b"Synthetic access-boundary fixture. No customer data."
        now = datetime.now(UTC)
        status, _ = request(
            "collector-raw-write",
            "mail-collector",
            "https://storage.azure.com",
            "PUT",
            blob,
            fixture,
            {
                "x-ms-blob-type": "BlockBlob",
                "x-ms-meta-capturedat": now.isoformat(),
                "x-ms-meta-expiresat": (now + timedelta(days=7)).isoformat(),
            },
        )
        record("collector_can_store_synthetic_raw_evidence", status, 201)
        for alias, expected in [("attribution", 200), ("content", 403), ("api", 403)]:
            status, source = request(
                "raw-read-" + alias, alias, "https://storage.azure.com", "GET", blob
            )
            record("raw_container_access_" + alias, status, expected)
            if status == 200:
                record("raw_evidence_bytes_match", source == fixture, True)
        status, _ = request(
            "out-of-container",
            "attribution",
            "https://storage.azure.com",
            "GET",
            f"https://{storage}.blob.core.windows.net/scope-control?restype=container&comp=list",
        )
        record("attribution_denied_other_container", status, 403)
        payload = base64.b64encode(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "fixture_ref": "authored_contract_example",
                    "message_ref": "synthetic-example",
                }
            ).encode()
        ).decode()
        xml = ("<QueueMessage><MessageText>" + payload + "</MessageText></QueueMessage>").encode()
        for queue in ["agent-evidence", "content-analysis"]:
            status, _ = request(
                "enqueue-" + queue,
                "mail-collector",
                "https://storage.azure.com",
                "POST",
                f"https://{storage}.queue.core.windows.net/{queue}/messages?messagettl=300",
                xml,
                {"Content-Type": "application/xml"},
            )
            record("collector_enqueue_reference_" + queue, status, 201)
        for alias, queue, expected in [
            ("attribution", "agent-evidence", 200),
            ("attribution", "content-analysis", 403),
            ("content", "content-analysis", 200),
            ("content", "agent-evidence", 403),
            ("api", "agent-evidence", 403),
            ("mail-collector", "agent-evidence", 403),
        ]:
            status, _ = request(
                "peek-" + alias + "-" + queue,
                alias,
                "https://storage.azure.com",
                "GET",
                f"https://{storage}.queue.core.windows.net/{queue}/messages?peekonly=true&numofmessages=1",
            )
            record("queue_access_" + alias + "_" + queue, status, expected)
        key_url = f"https://{vault}.vault.azure.net/keys/evidence-signing"
        status, source = request(
            "signing-public-key",
            "attribution",
            "https://vault.azure.net",
            "GET",
            key_url + "?api-version=7.4",
        )
        record("attribution_can_read_public_signing_key", status, 200)
        if status == 200:
            key = json.loads(source)["key"]
            record(
                "signing_key_private_material_not_exported",
                not any(field in key for field in ["d", "p", "q", "dp", "dq", "qi"]),
                True,
            )
            digest = base64.urlsafe_b64encode(hashlib.sha256(fixture).digest()).decode().rstrip("=")
            signed_status, signed = request(
                "signing-positive",
                "attribution",
                "https://vault.azure.net",
                "POST",
                key["kid"] + "/sign?api-version=7.4",
                json.dumps({"alg": "RS256", "value": digest}).encode(),
                {"Content-Type": "application/json"},
            )
            record("attribution_can_sign_evidence_digest", signed_status, 200)
            for alias in ["content", "api", "mail-collector"]:
                denied, _ = request(
                    "signing-negative-" + alias,
                    alias,
                    "https://vault.azure.net",
                    "POST",
                    key["kid"] + "/sign?api-version=7.4",
                    json.dumps({"alg": "RS256", "value": digest}).encode(),
                    {"Content-Type": "application/json"},
                )
                record("signing_denied_" + alias, denied, 403)
            if signed_status == 200:
                verified, value = request(
                    "signature-verification",
                    "api",
                    "https://vault.azure.net",
                    "POST",
                    key["kid"] + "/verify?api-version=7.4",
                    json.dumps(
                        {"alg": "RS256", "digest": digest, "value": json.loads(signed)["value"]}
                    ).encode(),
                    {"Content-Type": "application/json"},
                )
                record(
                    "api_can_verify_without_signing",
                    verified == 200 and json.loads(value).get("value") is True,
                    True,
                )

    if section in {"all", "audit"}:
        if not captured:
            raw = (directory / "allowed-mailbox.response.private").read_bytes()
            captured = next(m for m in json.loads(raw)["value"] if "CLAUDE-01" in m["subject"])
        sent = datetime.fromisoformat(captured["sentDateTime"].replace("Z", "+00:00"))
        query = {
            "displayName": "AgentTrace synthetic access verification",
            "filterStartDateTime": (sent - timedelta(minutes=2)).isoformat(),
            "filterEndDateTime": (sent + timedelta(minutes=2)).isoformat(),
            "recordTypeFilters": ["exchangeItem"],
            "operationFilters": ["Send"],
            "userPrincipalNameFilters": [config["mailbox"]],
        }
        status, source = request(
            "audit-query",
            "audit-collector",
            "https://graph.microsoft.com",
            "POST",
            "https://graph.microsoft.com/v1.0/security/auditLog/queries",
            json.dumps(query).encode(),
            {"Content-Type": "application/json"},
        )
        record("audit_identity_can_create_bounded_read_query", status in {201, 202}, True)
        if status in {201, 202}:
            query_id = json.loads(source)["id"]
            uri = "https://graph.microsoft.com/v1.0/security/auditLog/queries/" + quote(
                query_id, safe=""
            )
            for attempt in range(18):
                poll, state = request(
                    "audit-query-state",
                    "audit-collector",
                    "https://graph.microsoft.com",
                    "GET",
                    uri,
                )
                state = json.loads(state).get("status") if poll == 200 else "unavailable"
                if state in {"succeeded", "failed", "cancelled", "unavailable"}:
                    break
                if attempt % 3 == 0:
                    print(json.dumps({"audit_read_query": "pending"}), flush=True)
                time.sleep(10)
            record("audit_read_query_completes", state, "succeeded")
            if state == "succeeded":
                code, records = request(
                    "audit-query-records",
                    "audit-collector",
                    "https://graph.microsoft.com",
                    "GET",
                    uri + "/records?$top=20",
                )
                record("audit_identity_can_read_query_records", code, 200)
                if code == 200:
                    values = json.loads(records).get("value", [])
                    record(
                        "selected_synthetic_send_evidence_available",
                        any(
                            captured["internetMessageId"] in json.dumps(record) for record in values
                        ),
                        True,
                    )

    if section in {"all", "logs"}:
        inventory = json.loads((directory / "resource-inventory.private.json").read_text())
        workspace = next(
            item
            for item in inventory
            if item["type"].lower() == "microsoft.operationalinsights/workspaces"
            and item["location"] == "eastus"
        )
        prefix = [*azure_cli_prefix()]
        common = ["--subscription", config["subscription"], "--only-show-errors", "-o", "json"]
        result = subprocess.run(
            [
                *prefix,
                "monitor",
                "log-analytics",
                "workspace",
                "show",
                "--resource-group",
                "kb-agentdemo",
                "--workspace-name",
                workspace["name"],
                *common,
            ],
            capture_output=True,
            timeout=60,
            check=True,
        )
        customer = json.loads(result.stdout)["customerId"]
        group = (
            "/subscriptions/" + config["subscription"] + "/resourceGroups/kb-agentdemo/providers/"
        )
        resources = [
            group + "Microsoft.KeyVault/vaults/" + config["azure_access"]["vaultName"],
            group
            + "Microsoft.Storage/storageAccounts/"
            + config["azure_access"]["storageName"]
            + "/blobServices/default",
            group
            + "Microsoft.Storage/storageAccounts/"
            + config["azure_access"]["storageName"]
            + "/queueServices/default",
        ]
        scope_list = ",".join("'" + value.lower() + "'" for value in resources)
        query = (
            "union isfuzzy=true AzureDiagnostics,StorageBlobLogs,StorageQueueLogs | where TimeGenerated > ago(120m) | where tolower(_ResourceId) in ("
            + scope_list
            + ") | summarize event_count=count(), denied_count=countif(tostring(column_ifexists('StatusCode',''))=='403' or tostring(column_ifexists('ResultSignature','')) has 'Forbidden' or tostring(column_ifexists('ResultType','')) has 'Forbidden')"
        )
        result = subprocess.run(
            [
                *prefix,
                "monitor",
                "log-analytics",
                "query",
                "--workspace",
                customer,
                "--analytics-query",
                query,
                *common,
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        (directory / "resource-access-log-query.response.private").write_bytes(result.stdout)
        if result.returncode:
            (directory / "resource-access-log-query.error.private.txt").write_bytes(result.stderr)
            raise RuntimeError("resource_access_log_query_unavailable")
        counts = json.loads(result.stdout)[0]
        record("resource_access_events_actually_ingested", int(counts["event_count"]) > 0, True)
        record(
            "denied_identity_access_events_actually_ingested", int(counts["denied_count"]) > 0, True
        )

    if section in {"all", "api"}:
        access = identities["access-test"]
        policy_data = {
            "tenant": config["tenant"],
            "audience": config["api_application_id"],
            "allowed_clients": [access["application"]["appId"]],
            "subjects": {
                access["service_principal"]["id"]: [config["mailbox_id"]],
                config["operator_id"]: [config["mailbox_id"]],
            },
            "messages": {"synthetic-example": config["mailbox_id"]},
        }
        policy_path = directory / "entra-api-authorization.private.json"
        policy_path.write_text(json.dumps(policy_data), encoding="utf-8")
        access_token = token("access-test", "api://" + config["api_application_id"])
        principal = EntraTokenValidator(
            AuthorizationPolicy.load(policy_path, local_synthetic=True)
        ).validate(access_token)
        record(
            "actual_entra_api_token_has_expected_viewer_identity",
            principal.subject == access["service_principal"]["id"]
            and principal.roles == frozenset({"Detection.Viewer"}),
            True,
        )
        created = subprocess.run(
            [
                "docker",
                "compose",
                "--project-name",
                "agenttrace-foundation",
                "--file",
                "compose.yaml",
                "run",
                "--rm",
                "--no-deps",
                "collector-tools",
                "enqueue-example",
                "--key",
                uuid4().hex,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        decision_id = json.loads(created.stdout)["decision_id"]
        env = dict(
            os.environ,
            AGENTTRACE_AUTHORIZATION_FILE=str(policy_path),
            AGENTTRACE_DATABASE_USER="agenttrace_api",
            AGENTTRACE_DATABASE_PASSWORD_FILE=str(ROOT / "work/local/roles/api-password"),
            AGENTTRACE_DATABASE_HOST="127.0.0.1",
            AGENTTRACE_DATABASE_PORT="55432",
        )
        log = (directory / "entra-api-runtime.private.log").open("wb")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "agenttrace_foundation.api:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8091",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            for _ in range(30):
                if process.poll() is not None:
                    raise RuntimeError("entra_api_test_process_failed")
                try:
                    with urlopen("http://127.0.0.1:8091/health/live", timeout=1):
                        break
                except OSError:
                    time.sleep(0.5)
            url = "http://127.0.0.1:8091/v1/decisions/" + decision_id
            for _ in range(20):
                status, _ = request(
                    "entra-api-positive",
                    "access-test",
                    "api://" + config["api_application_id"],
                    "GET",
                    url,
                )
                if status != 404:
                    break
                time.sleep(0.5)
            record("actual_entra_token_authorizes_live_http_decision", status, 200)
            wrong, _ = request(
                "entra-api-wrong-audience",
                "mail-collector",
                "https://graph.microsoft.com",
                "GET",
                url,
            )
            record("actual_microsoft_wrong_audience_token_rejected_by_backend", wrong, 401)
            try:
                with urlopen(url, timeout=5) as response:
                    missing = response.status
            except HTTPError as error:
                missing = error.code
            record("live_backend_denies_missing_token", missing, 401)
        finally:
            process.terminate()
            process.wait(timeout=15)
            log.close()
        runtime_log = (directory / "entra-api-runtime.private.log").read_text(encoding="utf-8")
        record(
            "runtime_security_events_are_emitted_without_token_or_body",
            '"event":"token_validation"' in runtime_log
            and access_token not in runtime_log
            and config["mailbox"] not in runtime_log
            and "Synthetic test only." not in runtime_log,
            True,
        )

    report = {
        "verified_at": datetime.now(UTC).isoformat(),
        "section": section,
        "cases": cases,
        "all_pass": bool(cases) and all(case["passed"] for case in cases),
        "mail_mutations_attempted": 0,
        "public_text_uploads": 0,
        "scope": "effective synthetic access validation; no accuracy or production-readiness claim",
    }
    output = ROOT / "work/reports" / ("secure-access-live-" + section + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["all_pass"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--section",
        choices=["all", "mailbox", "configuration", "azure", "audit", "logs", "api"],
        default="all",
    )
    arguments = parser.parse_args()
    try:
        raise SystemExit(verify(arguments.config, arguments.section))
    except Exception as error:
        import traceback

        (arguments.config.resolve().parent / "live-verification-error.private.txt").write_text(
            traceback.format_exc(), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "live_verification": "failed",
                    "error_type": type(error).__name__,
                    "details": "ignored_private_diagnostic",
                }
            ),
            flush=True,
        )
        raise SystemExit(2) from None
