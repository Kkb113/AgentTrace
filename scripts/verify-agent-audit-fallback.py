"""Recheck the owner's fixed synthetic Claude email using independent Send audit evidence."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from agenttrace_feasibility.audit import CLAUDE_CONNECTOR_APP_ID, assess_audit_capture
from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.contracts import IngestionError
from agenttrace_ingestion.transport import MicrosoftTransport

ROOT = Path(__file__).resolve().parents[1]
SUBJECT = "AgentTrace synthetic test: AT-GRAPH-ACTIVITY-01"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume", action="store_true", help="Resume the saved exact bounded audit query"
    )
    args = parser.parse_args()
    directory = ROOT / "work/private/graph-activity"
    baseline = ROOT / "work/private/secure-access"
    config = json.loads(
        (baseline / "sandbox-settings.private.json").read_text(encoding="utf-8-sig")
    )
    identities = json.loads((baseline / "workload-identities.private.json").read_text())

    def transport(alias):
        identity = identities[alias]
        provider = CertificateTokenProvider(
            config["tenant"],
            identity["application"]["appId"],
            identity["certificate"]["thumbprint"],
            ROOT / "scripts/manage-workload-certificate.ps1",
        )
        return MicrosoftTransport(
            lambda *, force_refresh=False: provider.token(
                "https://graph.microsoft.com", force_refresh=force_refresh
            )
        )

    mail, audit = transport("mail-collector"), transport("audit-collector")
    base = "https://graph.microsoft.com/v1.0/users/" + quote(config["mailbox_id"], safe="")
    headers = {"Prefer": 'IdType="ImmutableId"'}
    folder = mail.request("GET", base + "/mailFolders/sentitems?$select=id", headers=headers)
    response = mail.request(
        "GET",
        base
        + "/mailFolders/sentitems/messages?"
        + urlencode(
            {
                "$filter": "subject eq '" + SUBJECT + "'",
                "$select": "id,subject,parentFolderId,internetMessageId,sentDateTime,from,isDraft,internetMessageHeaders",
                "$top": "5",
            }
        ),
        headers=headers,
    )
    messages = response.get("value", [])
    (directory / "fallback-synthetic-message.private.json").write_text(json.dumps(response))
    if (
        response.get("@odata.nextLink")
        or len(messages) != 1
        or messages[0].get("subject") != SUBJECT
    ):
        raise RuntimeError("fixed_synthetic_sent_copy_missing_or_ambiguous")
    message = messages[0]
    # Resolve only a legacy sender DN against this exact message's captured From header.
    if (
        message.get("from", {})
        .get("emailAddress", {})
        .get("address", "")
        .casefold()
        .startswith("/o=")
    ):
        from email.utils import parseaddr

        from_headers = [
            h["value"]
            for h in message.get("internetMessageHeaders", [])
            if h["name"].casefold() == "from"
        ]
        if len(from_headers) == 1:
            message["captured_mime_from_address"] = parseaddr(from_headers[0])[1]
    sent = datetime.fromisoformat(message["sentDateTime"].replace("Z", "+00:00"))
    if not timedelta(0) <= datetime.now(UTC) - sent <= timedelta(days=7):
        raise RuntimeError("synthetic_message_outside_raw_evidence_horizon")
    publisher = subprocess.run(
        [
            *azure_cli_prefix(),
            "rest",
            "--method",
            "get",
            "--url",
            "https://graph.microsoft.com/v1.0/servicePrincipals?"
            + urlencode(
                {
                    "$filter": "appId eq '" + CLAUDE_CONNECTOR_APP_ID + "'",
                    "$select": "appId,verifiedPublisher",
                }
            ),
            "--subscription",
            config["subscription"],
            "--only-show-errors",
            "-o",
            "json",
        ],
        capture_output=True,
        timeout=60,
    )
    (directory / "fallback-enrolled-publisher.private.json").write_bytes(publisher.stdout)
    if publisher.returncode:
        raise RuntimeError("enrolled_publisher_read_unavailable")
    publishers = json.loads(publisher.stdout)["value"]
    publisher_verified = (
        len(publishers) == 1
        and publishers[0]["appId"] == CLAUDE_CONNECTOR_APP_ID
        and bool(publishers[0].get("verifiedPublisher", {}).get("verifiedPublisherId"))
    )
    if not publisher_verified:
        raise RuntimeError("enrolled_connector_publisher_not_verified")
    query_root = "https://graph.microsoft.com/v1.0/security/auditLog/queries"
    query_body = {
        "displayName": "AgentTrace fixed synthetic independent attribution check",
        "filterStartDateTime": (sent - timedelta(minutes=2)).isoformat(),
        "filterEndDateTime": (sent + timedelta(minutes=2)).isoformat(),
        "recordTypeFilters": ["exchangeItem"],
        "operationFilters": ["Send"],
        "userPrincipalNameFilters": [config["mailbox"]],
    }
    query_file = directory / "fallback-audit-query.private.json"
    if args.resume:
        query = json.loads(query_file.read_text())
        same_window = all(
            datetime.fromisoformat(query[key].replace("Z", "+00:00"))
            == datetime.fromisoformat(query_body[key])
            for key in ["filterStartDateTime", "filterEndDateTime"]
        )
        same_filters = [v.casefold() for v in query.get("recordTypeFilters", [])] == [
            "exchangeitem"
        ] and all(
            query.get(key) == query_body[key]
            for key in ["displayName", "operationFilters", "userPrincipalNameFilters"]
        )
        if not same_window or not same_filters:
            raise RuntimeError("saved_query_does_not_match_fixed_synthetic_window")
    else:
        query = audit.request("POST", query_root, body=query_body)
        query_file.write_text(json.dumps(query))
    query_url = query_root + "/" + quote(query["id"], safe="")
    status = None
    for attempt in range(24):
        try:
            state = audit.request("GET", query_url)
        except IngestionError as error:
            if not error.retryable or error.retry_after > 60:
                raise
            time.sleep(max(5, error.retry_after))
            continue
        (directory / "fallback-audit-state.private.json").write_text(json.dumps(state))
        status = state.get("status")
        if status in {"succeeded", "failed", "cancelled"}:
            break
        if attempt % 6 == 0:
            print(json.dumps({"independent_send_audit_query": "pending"}), flush=True)
        time.sleep(10)
    records = []
    complete = status == "succeeded"
    if complete:
        page = audit.request("GET", query_url + "/records?$top=100")
        (directory / "fallback-audit-page.private.json").write_text(json.dumps(page))
        complete = not page.get("@odata.nextLink")
        for record in page.get("value", []):
            data = record.get("auditData", {})
            if isinstance(data, str):
                data = json.loads(data)
            if data.get("Item", {}).get("InternetMessageId") == message.get("internetMessageId"):
                records.append({**record, "auditData": data})
    result = assess_audit_capture(
        messages,
        records,
        tenant_id=config["tenant"],
        mailbox=config["mailbox"],
        subject=SUBJECT,
        sent_folder_id=folder["id"],
        first_seen=datetime.now(UTC),
        authenticated_live_capture=True,
        complete=complete,
    )
    # Public report excludes raw IDs, addresses, request URLs and message headers.
    finding = result["findings"]["agent_send_attribution"]
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "case": "owner_prepared_fresh_claude_synthetic_test",
        "capture_basis": "live_certificate_authenticated_Microsoft_Graph_mail_and_Exchange_audit_APIs",
        "enrolled_connector_publisher_verified": publisher_verified,
        "bounded_audit_query_completed": complete,
        "agent_send_finding": {k: finding[k] for k in ["status", "flagged", "reason_codes"]},
        "supporting_observations": result["supporting_observations"],
        "graph_activity_log_records_required": False,
        "new_mail_permissions": False,
        "email_mutations": 0,
        "qualification_limit": "One enrolled-connector message; not an accuracy or universal-coverage measurement.",
    }
    report["independent_audit_attribution_passed"] = (
        complete and finding["status"] == "verified_agent"
    )
    (ROOT / "docs/evidence/agent-audit-fallback-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report), flush=True)
    return 0 if report["independent_audit_attribution_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
