"""Fresh read-only feasibility inventory of existing synthetic examples and identities.

Locators select items; their actor labels never enter detection. No audit search is
created, no category is changed, and no identity/resource is provisioned.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_feasibility.mail_monitor import FIELDS, AuditJob, build_sources, initial_result
from agenttrace_feasibility.outlook_baseline import read_baseline
from agenttrace_feasibility.validation import InputError, load_json, timestamp
from agenttrace_ingestion.contracts import IngestionError

ROOT = Path(__file__).resolve().parents[1]
GRAPH = "https://graph.microsoft.com/v1.0"


def decode_cli_json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        # Azure CLI's isolated Windows Python can use the console code page.
        return json.loads(raw.decode("cp1252"))


def inspect(locators: Path, output: Path) -> dict:
    private = (ROOT / "work/private").resolve()
    if not locators.resolve().is_relative_to(private) or not output.resolve().is_relative_to(
        private
    ):
        raise InputError("private_input_and_output_required")
    config = load_json(locators)
    if set(config) != {"cases"} or not 1 <= len(config["cases"]) <= 3:
        raise InputError("bounded_synthetic_locator_list_required")
    for locator in config["cases"]:
        if not isinstance(locator.get("expected_subject"), str) or not locator[
            "expected_subject"
        ].startswith(("AgentTrace demo ", "AgentTrace synthetic test:")):
            raise InputError("synthetic_item_required")
    output.mkdir(exist_ok=False, parents=True)
    policy = read_baseline(ROOT / "config/outlook-production-baseline.json")
    settings, mail, audit = build_sources(private / "secure-access", exchange_audit=True)
    mail.prepare()
    captures = {}

    def capture(alias, data):
        raw = json.dumps(data, sort_keys=True).encode()
        (output / (alias + ".private.json")).write_bytes(raw)
        captures[alias] = hashlib.sha256(raw).hexdigest()

    now = datetime.now(UTC)
    cases = []
    expires = now + timedelta(days=policy.raw_retention_days)
    for index, locator in enumerate(config["cases"]):
        if locator.get("message_id"):
            selected = {"id": locator["message_id"]}
        else:
            mid = locator["internet_message_id"]
            copies = mail.pages(
                mail.base
                + "/messages?"
                + urlencode(
                    {
                        "$filter": "internetMessageId eq '" + mid.replace("'", "''") + "'",
                        "$select": FIELDS,
                        "$top": "100",
                    }
                )
            )
            received = [
                m
                for m in copies
                if m.get("parentFolderId") not in mail.excluded and m.get("isDraft") is False
            ]
            if len(received) != 1:
                raise InputError("synthetic_received_copy_missing_or_ambiguous")
            selected = received[0]
        detail = mail.detail(selected)
        if (
            detail.get("subject") != locator["expected_subject"]
            or detail.get("isDraft") is not False
        ):
            raise InputError("selected_synthetic_item_mismatch")
        if not locator["expected_subject"].startswith(
            ("AgentTrace demo ", "AgentTrace synthetic test:")
        ):
            raise InputError("synthetic_item_required")
        expires = min(expires, timestamp(detail["receivedDateTime"]) + timedelta(days=7))
        if expires <= now:
            raise InputError("synthetic_capture_retention_expired")
        capture("message-" + str(index), detail)
        conservative = initial_result(detail, settings["mailbox"])
        demo = initial_result(detail, settings["mailbox"], demo_heuristic=True)
        item = {
            "case_ref": locator["case_ref"],
            "owner_reported_actor": locator["owner_reported_actor"],
            "truth_basis": "owner_prepared_report_not_independent_accuracy_label",
            "demo_label": demo["classification"],
            "demo_qualification": demo["qualification"],
            "conservative_header_only_result": conservative["classification"],
            "legacy_authenticated_audit_recheck": "not_applicable",
        }
        if locator.get("audit_query_id"):
            if audit is None or not audit.eligible(detail):
                raise InputError("enrolled_audit_path_unavailable")
            query_id = locator["audit_query_id"]
            query = audit.audit.request("GET", audit.root + "/" + quote(query_id, safe=""))
            sent = timestamp(detail["sentDateTime"])
            if (
                timestamp(query["filterStartDateTime"]) != sent - timedelta(minutes=2)
                or timestamp(query["filterEndDateTime"]) != sent + timedelta(minutes=2)
                or query.get("operationFilters") != ["Send"]
                or [v.casefold() for v in query.get("recordTypeFilters", [])] != ["exchangeitem"]
                or [v.casefold() for v in query.get("userPrincipalNameFilters", [])]
                != [settings["mailbox"].casefold()]
            ):
                raise InputError("saved_query_scope_or_window_mismatch")
            capture("audit-query", query)
            result = audit.step(AuditJob(detail, conservative, now, query_id=query_id), now)
            item["legacy_authenticated_audit_recheck"] = (
                result["classification"] if result else "unavailable_or_pending"
            )
        cases.append(item)

    # Bounded complete non-hidden folder inventory; names/IDs stay private.
    folders, pending, visited = (
        [],
        [
            mail.base
            + "/mailFolders?"
            + urlencode(
                {"$select": "id,displayName,parentFolderId,childFolderCount", "$top": "100"}
            )
        ],
        set(),
    )
    while pending:
        url = pending.pop(0)
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not parsed.path.startswith(urlsplit(mail.base).path + "/mailFolders")
            or url in visited
            or len(visited) >= 100
        ):
            raise InputError("folder_inventory_scope_or_limit")
        visited.add(url)
        page = mail.transport.request("GET", url)
        for folder in page["value"]:
            folders.append(folder)
            if folder.get("childFolderCount", 0):
                pending.append(
                    mail.base
                    + "/mailFolders/"
                    + quote(folder["id"], safe="")
                    + "/childFolders?$select=id,displayName,parentFolderId,childFolderCount&$top=100"
                )
        if page.get("@odata.nextLink"):
            pending.append(page["@odata.nextLink"])
    capture("folder-inventory", {"value": folders})
    denied = False
    try:
        mail.transport.request(
            "GET",
            GRAPH
            + "/users/"
            + str(UUID(settings["control_mailbox_id"]))
            + "/messages?$select=id&$top=1",
        )
    except IngestionError as error:
        denied = error.code == "source_access_denied"
    if not denied:
        raise InputError("negative_mailbox_scope_check_failed")

    # Existing Entra app-role assignments are inventory only. Exchange RBAC is
    # separately recorded; these grants alone cannot establish all effective rights.
    identities = load_json(private / "secure-access/workload-identities.private.json")

    def admin_get(path):
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                "rest",
                "--method",
                "GET",
                "--url",
                GRAPH + "/" + path,
                "--subscription",
                settings["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=60,
            shell=False,
        )
        if result.returncode or len(result.stdout) > 2_097_152:
            raise InputError("existing_identity_inventory_unavailable")
        data = decode_cli_json(result.stdout)
        if data.get("@odata.nextLink"):
            raise InputError("existing_identity_inventory_incomplete")
        return data

    resource = admin_get(
        "servicePrincipals?"
        + urlencode(
            {"$filter": "appId eq '00000003-0000-0000-c000-000000000000'", "$select": "id,appRoles"}
        )
    )["value"]
    if len(resource) != 1:
        raise InputError("graph_resource_identity_ambiguous")
    role_names = {r["id"]: r["value"] for r in resource[0]["appRoles"]}
    roles = {}
    for alias in ("mail-collector", "audit-collector"):
        identity = identities[alias]["service_principal"]["id"]
        assignments = admin_get("servicePrincipals/" + str(UUID(identity)) + "/appRoleAssignments")
        capture(alias + "-app-grants", assignments)
        roles[alias] = sorted(
            role_names[a["appRoleId"]]
            for a in assignments["value"]
            if a["resourceId"] == resource[0]["id"]
        )
        if set(roles[alias]) & {
            "Mail.Send",
            "Mail.ReadWrite",
            "Mail.ReadWrite.Shared",
            "Mail-Advanced.ReadWrite.All",
            "MailboxSettings.ReadWrite",
        }:
            raise InputError("unexpected_mail_write_or_send_grant")
    report = {
        "executed_at": now.isoformat(),
        "evidence_expires_at": expires.isoformat(),
        "capture_basis": "fresh_authenticated_graph_and_existing_audit_query_reads",
        "cases": cases,
        "folder_inventory_complete": True,
        "visible_folder_count": len(folders),
        "receiving_folder_count": sum(f["id"] not in mail.excluded for f in folders),
        "control_mailbox_access_denied": denied,
        "entra_graph_app_roles": roles,
        "effective_rights_limit": "App roles are not a complete Exchange RBAC inventory; prior scoped assignment evidence is historical. No category write probe attempted.",
        "human_rule": policy.human_rule_status,
        "production_received_copy_qualification": "pending_separate_attack_and_link_tests",
        "mail_mutations": 0,
        "new_permissions": 0,
        "new_azure_resources": 0,
        "raw_capture_hashes": dict(captures),
        "qualification_limit": "Feasibility only; not production accuracy, human-source qualification or category-write enablement.",
    }
    capture("inspection-report", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locators", type=Path, required=True)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.report.resolve().is_relative_to((ROOT / "work/reports").resolve()):
            raise InputError("report_output_out_of_scope")
        report = inspect(args.locators, args.private_output)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))
        return 0
    except (InputError, IngestionError) as error:
        print(json.dumps({"error": str(error), "mail_mutations": 0}))
        return 1
    except Exception as error:
        import traceback

        diagnostic = {
            "exception_type": type(error).__name__,
            "frames": [
                {"function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)
            ],
        }
        if (
            args.private_output.resolve().is_relative_to((ROOT / "work/private").resolve())
            and args.private_output.is_dir()
        ):
            (args.private_output / "diagnostic.private.json").write_text(
                json.dumps(diagnostic), encoding="utf-8"
            )
        print(
            json.dumps({"error": "outlook_baseline_inspection_unavailable_no_mutation_attempted"})
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
