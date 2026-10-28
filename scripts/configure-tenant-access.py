"""Idempotent, operator-run setup of the approved detection-only Entra registrations.

Uses the existing administrator session. Private IDs and public certificate references
are saved only in ignored configuration. It never obtains or exposes a private key.
Exchange scoping is a separate reviewed script; no Entra mailbox role is granted here.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "https://graph.microsoft.com/v1.0/"
GRAPH_APP = "00000003-0000-0000-c000-000000000000"
ALIASES = ("mail-collector", "audit-collector", "attribution", "content", "api", "access-test")
TAG = "AgentTraceSyntheticSandbox"


class Administrator:
    def __init__(self, config: dict, directory: Path):
        self.config = config
        self.directory = directory

    def graph(self, method: str, path: str, body: dict | None = None) -> dict:
        arguments = [*azure_cli_prefix(), "rest", "--method", method, "--url", GRAPH + path]
        if body is not None:
            request = self.directory / "graph-request.private.json"
            request.write_text(json.dumps(body), encoding="utf-8")
            arguments += ["--body", "@" + str(request)]
        arguments += [
            "--subscription",
            self.config["subscription"],
            "--only-show-errors",
            "-o",
            "json",
        ]
        result = subprocess.run(arguments, capture_output=True, timeout=90, check=False)
        if result.returncode:
            (self.directory / "administrator-error.private.txt").write_bytes(result.stderr)
            raise RuntimeError("tenant_configuration_operation_failed_see_private_diagnostic")
        try:
            source = result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            # The Windows Azure CLI may explicitly emit the active ANSI code page.
            source = result.stdout.decode("cp1252")
        return json.loads(source) if source.strip() else {}

    def certificate(self, alias: str) -> dict:
        result = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(ROOT / "scripts/manage-workload-certificate.ps1"),
                "-Operation",
                "Create",
            ],
            input=json.dumps({"alias": alias}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("protected_workload_certificate_creation_failed")
        return json.loads(result.stdout)


def role_id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, "agenttrace:api-role:" + name))


def configure(config_path: Path) -> None:
    directory = config_path.resolve().parent
    if not directory.is_relative_to((ROOT / "work/private").resolve()):
        raise ValueError("ignored_private_configuration_required")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config["resource_group"] != "kb-agentdemo" or config["region"] != "eastus":
        raise ValueError("unapproved_sandbox_target")
    baseline = json.loads((ROOT / "config/secure-access-baseline.json").read_text())
    if not baseline["synthetic_only"] or baseline["mailbox_send_or_write_grants"]:
        raise ValueError("accepted_detection_only_baseline_required")
    admin = Administrator(config, directory)
    manifest_path = directory / "workload-identities.private.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    def save() -> None:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    for alias in ALIASES:
        entry = manifest.setdefault(alias, {})
        if "certificate" not in entry:
            entry["certificate"] = admin.certificate(alias)
            save()
        if "application" not in entry:
            existing = admin.graph(
                "GET",
                "applications?$filter=displayName eq 'AgentTrace Sandbox "
                + alias
                + "'&$select=id,appId,tags",
            )
            matches = existing.get("value", [])
            if matches:
                if len(matches) != 1 or TAG not in matches[0].get("tags", []):
                    raise RuntimeError("ambiguous_existing_application_stop_for_review")
                entry["application"] = matches[0]
            else:
                certificate = entry["certificate"]
                body = {
                    "displayName": "AgentTrace Sandbox " + alias,
                    "signInAudience": "AzureADMyOrg",
                    "tags": [TAG],
                    "requiredResourceAccess": [],
                    "api": {"requestedAccessTokenVersion": 2},
                    "keyCredentials": [
                        {
                            "keyId": str(uuid4()),
                            "displayName": "sandbox-nonexportable-90-day",
                            "type": "AsymmetricX509Cert",
                            "usage": "Verify",
                            "key": certificate["certificate"],
                            "customKeyIdentifier": base64.b64encode(
                                bytes.fromhex(certificate["thumbprint"])
                            ).decode(),
                            "startDateTime": certificate["not_before"],
                            "endDateTime": certificate["not_after"],
                        }
                    ],
                }
                if alias == "api":
                    body["optionalClaims"] = {
                        "accessToken": [{"name": "idtyp", "essential": False}]
                    }
                    body["appRoles"] = [
                        {
                            "id": role_id(name),
                            "value": "Detection." + name,
                            "displayName": "Detection " + name,
                            "description": "Read-only detection " + name.lower(),
                            "allowedMemberTypes": ["User", "Application"]
                            if name == "Viewer"
                            else ["User"],
                            "isEnabled": True,
                        }
                        for name in ["Viewer", "Investigator", "Administrator"]
                    ]
                    body["api"]["oauth2PermissionScopes"] = [
                        {
                            "id": role_id("ReadScope"),
                            "value": "Detection.Read",
                            "type": "Admin",
                            "isEnabled": True,
                            "adminConsentDisplayName": "Read authorized AgentTrace detections",
                            "adminConsentDescription": "Read detection findings only within server-assigned mailbox scope.",
                        }
                    ]
                entry["application"] = admin.graph("POST", "applications", body)
            save()
        if "service_principal" not in entry:
            app_id = entry["application"]["appId"]
            found = admin.graph("GET", f"servicePrincipals?$filter=appId eq '{app_id}'")
            entry["service_principal"] = (
                found["value"][0]
                if found["value"]
                else admin.graph("POST", "servicePrincipals", {"appId": app_id, "tags": [TAG]})
            )
            save()
        print(
            json.dumps({"identity": alias, "registration": "ready", "private_key_exported": False}),
            flush=True,
        )

    api = manifest["api"]
    api_app, api_sp = api["application"]["appId"], api["service_principal"]["id"]
    admin.graph(
        "PATCH",
        "applications/" + api["application"]["id"],
        {"identifierUris": ["api://" + api_app]},
    )
    admin.graph("PATCH", "servicePrincipals/" + api_sp, {"appRoleAssignmentRequired": True})
    graph_sp = admin.graph(
        "GET", f"servicePrincipals?$filter=appId eq '{GRAPH_APP}'&$select=id,appRoles"
    )["value"][0]
    audit_role = next(
        role
        for role in graph_sp["appRoles"]
        if role["value"] == "AuditLogsQuery-Exchange.Read.All"
        and "Application" in role["allowedMemberTypes"]
        and role["isEnabled"]
    )
    for alias, resource, permission in [
        ("audit-collector", graph_sp["id"], audit_role["id"]),
        ("access-test", api_sp, role_id("Viewer")),
    ]:
        principal = manifest[alias]["service_principal"]["id"]
        existing = admin.graph("GET", f"servicePrincipals/{principal}/appRoleAssignments")["value"]
        if not any(
            item["resourceId"] == resource and item["appRoleId"] == permission for item in existing
        ):
            admin.graph(
                "POST",
                f"servicePrincipals/{principal}/appRoleAssignments",
                {"principalId": principal, "resourceId": resource, "appRoleId": permission},
            )
    for name in ["Viewer", "Investigator", "Administrator"]:
        principal = config["operator_id"]
        existing = admin.graph("GET", f"users/{principal}/appRoleAssignments")["value"]
        if not any(
            item["resourceId"] == api_sp and item["appRoleId"] == role_id(name) for item in existing
        ):
            admin.graph(
                "POST",
                f"users/{principal}/appRoleAssignments",
                {"principalId": principal, "resourceId": api_sp, "appRoleId": role_id(name)},
            )
    config["api_application_id"] = api_app
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "setup": "complete",
                "mailbox_roles_granted_in_entra": 0,
                "exchange_audit_permission": "separate_explicitly_accepted_identity",
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args()
    if arguments.apply:
        configure(arguments.config)
    else:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "identities": ALIASES,
                    "mail_send_or_write_grants": False,
                    "azure_resources_created": False,
                }
            )
        )
