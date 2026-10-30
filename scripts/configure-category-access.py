"""Operator-only registration and exact retirement for approved category identities."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from agenttrace_feasibility.capabilities import azure_cli_prefix

ROOT = Path(__file__).resolve().parents[1]
TAG = "AgentTraceOutlookCategories-v1"
NAMES = {
    "category-writer": "AgentTrace Outlook Category Writer",
    "category-setup": "AgentTrace Outlook Category Setup",
}


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["plan", "register", "inspect", "retire-setup"])
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if directory != (ROOT / "work/private/outlook-categories").resolve():
        raise ValueError("exact_private_category_directory_required")
    settings = json.loads((directory / "proposal.private.json").read_text(encoding="utf-8-sig"))
    for key in ("tenant", "subscription", "mailbox_id", "control_mailbox_id"):
        UUID(settings[key])
    manifest_path = directory / "identities.private.json"
    identities = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    def graph(method: str, path: str, body: dict | None = None) -> dict:
        arguments = [
            *azure_cli_prefix(),
            "rest",
            "--method",
            method,
            "--url",
            "https://graph.microsoft.com/v1.0/" + path,
        ]
        if body is not None:
            target = directory / "admin-request.private.json"
            target.write_text(json.dumps(body), encoding="utf-8")
            arguments += ["--body", "@" + str(target)]
        response = subprocess.run(
            [
                *arguments,
                "--subscription",
                settings["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=60,
            check=False,
            shell=False,
        )
        if response.returncode:
            (directory / "admin-error.private.txt").write_bytes(response.stderr)
            raise ValueError("category_administrator_request_failed")
        return json.loads(response.stdout.decode("utf-8-sig")) if response.stdout.strip() else {}

    def save() -> None:
        manifest_path.write_text(json.dumps(identities, indent=2) + "\n", encoding="utf-8")

    account = subprocess.run(
        [
            *azure_cli_prefix(),
            "account",
            "show",
            "--subscription",
            settings["subscription"],
            "-o",
            "json",
            "--only-show-errors",
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if account.returncode or json.loads(account.stdout).get("tenantId") != settings["tenant"]:
        raise ValueError("category_administrator_tenant_mismatch")
    if args.operation == "plan":
        print(
            json.dumps(
                {
                    "approved_mailbox_count": 1,
                    "new_azure_resources": 0,
                    "registrations": list(NAMES),
                    "automatic_application_enabled": False,
                }
            )
        )
        return 0
    if args.operation == "register":
        for alias, name in NAMES.items():
            entry = identities.setdefault(alias, {})
            if entry.get("retired_at"):
                raise ValueError("retired_identity_requires_new_review")
            if "certificate" not in entry:
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
                    raise ValueError("category_certificate_creation_failed")
                entry["certificate"] = json.loads(result.stdout)
                save()
            if "application" not in entry:
                found = graph(
                    "GET",
                    "applications?$filter=displayName eq '"
                    + name
                    + "'&$select=id,appId,displayName,tags",
                )
                if found.get("value"):
                    raise ValueError("unrecorded_existing_category_registration")
                cert = entry["certificate"]
                entry["application"] = graph(
                    "POST",
                    "applications",
                    {
                        "displayName": name,
                        "signInAudience": "AzureADMyOrg",
                        "tags": [TAG],
                        "requiredResourceAccess": [],
                        "api": {"requestedAccessTokenVersion": 2},
                        "keyCredentials": [
                            {
                                "keyId": str(uuid4()),
                                "displayName": alias,
                                "type": "AsymmetricX509Cert",
                                "usage": "Verify",
                                "key": cert["certificate"],
                                "customKeyIdentifier": base64.b64encode(
                                    bytes.fromhex(cert["thumbprint"])
                                ).decode(),
                                "startDateTime": cert["not_before"],
                                "endDateTime": cert["not_after"],
                            }
                        ],
                    },
                )
                save()
            app = entry["application"]
            actual = graph(
                "GET",
                "applications/"
                + app["id"]
                + "?$select=id,appId,displayName,tags,requiredResourceAccess",
            )
            if (
                actual["appId"] != app["appId"]
                or actual["displayName"] != name
                or TAG not in actual.get("tags", [])
                or actual.get("requiredResourceAccess")
            ):
                raise ValueError("category_registration_changed")
            if "service_principal" not in entry:
                found = graph("GET", "servicePrincipals?$filter=appId eq '" + app["appId"] + "'")
                if len(found.get("value", [])) > 1:
                    raise ValueError("category_principal_ambiguous")
                entry["service_principal"] = (
                    found["value"][0]
                    if found["value"]
                    else graph("POST", "servicePrincipals", {"appId": app["appId"], "tags": [TAG]})
                )
                save()
            print(
                json.dumps({"identity": alias, "registered": True, "mail_send_granted": False}),
                flush=True,
            )
    inventory = {}
    for alias, entry in identities.items():
        if entry.get("retired_at"):
            continue
        sp = entry["service_principal"]["id"]
        inventory[alias] = {
            "application_roles": graph("GET", f"servicePrincipals/{sp}/appRoleAssignments"),
            "delegated_grants": graph("GET", f"oauth2PermissionGrants?$filter=clientId eq '{sp}'"),
            "directory_membership": graph("GET", f"servicePrincipals/{sp}/memberOf"),
        }
        if any(v.get("value") or v.get("@odata.nextLink") for v in inventory[alias].values()):
            raise ValueError("unexpected_additive_category_permission")
    (directory / "entra-inventory.private.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8"
    )
    if args.operation == "retire-setup":
        entry = identities["category-setup"]
        app, sp = entry["application"], entry["service_principal"]
        actual = graph("GET", "applications/" + app["id"] + "?$select=id,appId,displayName,tags")
        if (
            actual["appId"] != app["appId"]
            or actual["displayName"] != NAMES["category-setup"]
            or TAG not in actual.get("tags", [])
        ):
            raise ValueError("setup_retirement_target_mismatch")
        # Exchange assignment/pointer removal must be independently recorded first.
        retired = json.loads(
            (directory / "exchange-retiresetup.private.json").read_text(encoding="utf-8-sig")
        )
        if (
            not retired["category-setup"]["exchange_assignments_removed"]
            or not retired["category-setup"]["exchange_pointer_removed"]
        ):
            raise ValueError("exchange_setup_retirement_required")
        graph("PATCH", "servicePrincipals/" + sp["id"], {"accountEnabled": False})
        graph("DELETE", "servicePrincipals/" + sp["id"])
        graph("DELETE", "applications/" + app["id"])
        entry["retired_at"] = datetime.now(UTC).isoformat()
        save()
        print(
            json.dumps(
                {"setup_registration_retired": True, "certificate_retirement_still_required": True}
            )
        )
    print(
        json.dumps(
            {
                "category_identity_inventory_verified": True,
                "entra_application_or_delegated_grants": 0,
                "automatic_application_enabled": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (ValueError, KeyError, TypeError, OSError, subprocess.TimeoutExpired):
        print(json.dumps({"error": "category_administration_failed_see_private_diagnostic"}))
        raise SystemExit(2) from None
