"""Operator-only read probe; no app provisioning or email execution capability."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from email.utils import getaddresses
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

import msal

from .audit import assess_audit_capture
from .mime import parse_mime
from .validation import InputError, digest, load_json, object_fields, record_list, text, timestamp

READER_SCOPES = ["Mail.Read", "AuditLogsQuery-Exchange.Read.All"]
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise InputError("graph_redirect_rejected")


def validate_settings(path: Path) -> dict:
    config = object_fields(
        load_json(path), {"tenant_id", "client_id", "operator_id", "mailbox", "subjects"}
    )
    for key in ["tenant_id", "client_id", "operator_id"]:
        try:
            UUID(text(config[key]))
        except ValueError as exc:
            raise InputError("valid_identity_guid_required") from exc
    text(config["mailbox"])
    subjects = record_list(config["subjects"])
    if not 1 <= len(subjects) <= 3 or len(set(map(str, subjects))) != len(subjects):
        raise InputError("one_to_three_unique_synthetic_subjects_required")
    for subject in subjects:
        if not text(subject).startswith("AgentTrace synthetic test:"):
            raise InputError("only_marked_synthetic_subjects_allowed")
    return config


class GraphReader:
    def __init__(self, token: str):
        self._token = token
        self._opener = build_opener(NoRedirect())

    def request(self, path: str, body: dict | None = None, *, raw: bool = False):
        route = path.split("?", 1)[0]
        allowed_get = (
            route == "me/messages"
            or route == "me/mailFolders/sentitems"
            or (route.startswith("me/messages/") and route.endswith("/$value"))
            or route.startswith("security/auditLog/queries/")
        )
        if (
            urlsplit(path).scheme
            or path.startswith("/")
            or ".." in route.split("/")
            or (body is not None and route != "security/auditLog/queries")
            or (body is None and not allowed_get)
        ):
            raise InputError("reader_operation_not_allowlisted")
        headers = {"Authorization": "Bearer " + self._token, "Prefer": 'IdType="ImmutableId"'}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = Request("https://graph.microsoft.com/v1.0/" + path, data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=45) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise InputError(f"graph_read_http_{exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            raise InputError("graph_read_unavailable") from exc
        if len(payload) > MAX_RESPONSE_BYTES:
            raise InputError("graph_response_too_large")
        return payload if raw else json.loads(payload)


def _save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def validate_reused_query(query: dict, expected: dict) -> None:
    valid = (
        query.get("keywordFilter") == expected["keywordFilter"]
        and query.get("userPrincipalNameFilters") == expected["userPrincipalNameFilters"]
        and set(query.get("operationFilters", [])) == set(expected["operationFilters"])
        and [s.casefold() for s in query.get("recordTypeFilters", [])] == ["exchangeitem"]
        and timestamp(query.get("filterStartDateTime"))
        == timestamp(expected["filterStartDateTime"])
        and timestamp(query.get("filterEndDateTime")) == timestamp(expected["filterEndDateTime"])
    )
    if not valid:
        raise InputError("reused_audit_query_scope_mismatch")


def _collect_subject(
    reader: GraphReader, config: dict, subject: str, output: Path, reuse: Path | None = None
) -> dict:
    output.mkdir()
    page = reader.request(
        "me/messages?"
        + urlencode(
            {
                "$filter": "subject eq '" + subject.replace("'", "''") + "'",
                "$select": "id,internetMessageId,subject,parentFolderId,sentDateTime,receivedDateTime,isDraft,from",
                "$top": "5",
            }
        )
    )
    messages = [m for m in page.get("value", []) if m.get("subject") == subject]
    folder = reader.request("me/mailFolders/sentitems?$select=id")
    _save(output / "message-metadata.private.json", messages)
    sent = [m for m in messages if m.get("parentFolderId") == folder["id"]]
    records: list[dict] = []
    complete = not bool(page.get("@odata.nextLink"))
    query_status = "not_requested_ambiguous_sent_copy"
    if len(sent) == 1 and sent[0].get("internetMessageId") and complete:
        item = sent[0]
        raw = reader.request("me/messages/" + quote(item["id"], safe="") + "/$value", raw=True)
        mime = parse_mime(raw)
        ids = mime.get_all("Message-ID", [])
        if len(ids) != 1 or str(ids[0]).strip() != item["internetMessageId"]:
            raise InputError("live_mime_and_metadata_message_id_mismatch")
        senders = getaddresses([str(value) for value in mime.get_all("From", [])])
        if len(senders) == 1:
            item["captured_mime_from_address"] = senders[0][1]
        _save(output / "message-metadata.private.json", messages)
        (output / "sent-message.eml").write_bytes(raw)
        event_time = timestamp(item["sentDateTime"])
        query_body = {
            "displayName": "AgentTrace synthetic evidence search",
            "filterStartDateTime": (event_time - timedelta(minutes=2)).isoformat(),
            "filterEndDateTime": (event_time + timedelta(minutes=2)).isoformat(),
            "recordTypeFilters": ["exchangeItem"],
            "operationFilters": ["Send", "SendAs", "SendOnBehalf"],
            "userPrincipalNameFilters": [config["mailbox"]],
            "keywordFilter": item["internetMessageId"],
        }
        if reuse is not None and (reuse / "audit-query.private.json").is_file():
            previous = load_json(reuse / "audit-query.private.json")
            try:
                query_id = str(UUID(text(previous["id"])))
            except (KeyError, ValueError) as exc:
                raise InputError("invalid_reused_audit_query_id") from exc
            query = reader.request("security/auditLog/queries/" + query_id)
            validate_reused_query(query, query_body)
        else:
            query = reader.request("security/auditLog/queries", query_body)
        _save(output / "audit-query.private.json", query)
        query_path = "security/auditLog/queries/" + quote(text(query["id"]), safe="")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            status = reader.request(query_path)
            _save(output / "audit-status.private.json", status)
            query_status = status.get("status")
            if query_status in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(5)
        complete = query_status == "succeeded"
        if complete:
            rows = reader.request(query_path + "/records?$top=100")
            complete = not bool(rows.get("@odata.nextLink"))
            # Retain only exact target rows from the already tightly scoped query.
            records = [
                r
                for r in rows.get("value", [])
                if r.get("auditData", {}).get("Item", {}).get("InternetMessageId")
                == item["internetMessageId"]
            ]
            _save(output / "audit-records.private.json", records)
        _save(output / "mime-capture.private.json", {"mime_sha256": digest(raw)})
    else:
        complete = False
    first_seen = datetime.now(UTC)
    result = assess_audit_capture(
        messages,
        records,
        tenant_id=config["tenant_id"],
        mailbox=config["mailbox"],
        subject=subject,
        sent_folder_id=folder["id"],
        first_seen=first_seen,
        authenticated_live_capture=True,
        complete=complete,
    )
    result.update(
        observed_at=first_seen.isoformat(),
        audit_query_status=query_status,
        validation_basis="live_msgraph_capture_by_operator_reader_not_vendor_signed_receipt",
    )
    _save(output / "assessment.private.json", result)
    return result


def collect_reader_evidence(settings_path: Path, output: Path, reuse: Path | None = None) -> dict:
    config = validate_settings(settings_path)
    private_root = Path.cwd().resolve() / "work/private"
    if not output.resolve().is_relative_to(private_root) or output.exists():
        raise InputError("new_private_output_directory_required")
    if reuse is not None and (
        not reuse.resolve().is_relative_to(private_root) or not reuse.is_dir()
    ):
        raise InputError("private_search_capture_directory_required")
    app = msal.PublicClientApplication(
        config["client_id"],
        authority="https://login.microsoftonline.com/" + config["tenant_id"],
        exclude_scopes=["offline_access"],
    )
    print(
        json.dumps({"status": "microsoft_browser_sign_in", "token_cache": "memory_only"}),
        flush=True,
    )
    result = app.acquire_token_interactive(
        scopes=READER_SCOPES, login_hint=config["mailbox"], timeout=600
    )
    if "access_token" not in result:
        raise InputError("reader_authentication_failed")
    claims = result.get("id_token_claims", {})
    if claims.get("oid") != config["operator_id"] or claims.get("tid") != config["tenant_id"]:
        raise InputError("unexpected_authenticated_operator_or_tenant")
    granted = set(result.get("scope", "").split())
    if not set(READER_SCOPES) <= granted:
        raise InputError("approved_reader_scopes_not_effective")
    output.mkdir(parents=True)
    reader = GraphReader(result["access_token"])
    assessments = []
    for index, subject in enumerate(config["subjects"]):
        assessment = _collect_subject(
            reader,
            config,
            subject,
            output / f"message-{index + 1}",
            reuse / f"message-{index + 1}" if reuse is not None else None,
        )
        assessments.append(assessment)
        print(
            json.dumps(
                {
                    "status": "synthetic_message_assessed",
                    "test_index": index + 1,
                    "agent_finding": assessment["findings"]["agent_send_attribution"]["status"],
                }
            ),
            flush=True,
        )
    summary = {
        "completed_at": datetime.now(UTC).isoformat(),
        "authentication": "msal_browser_pkce_validated_operator_and_tenant",
        "tokens_written_to_disk": False,
        "new_azure_resources_created": 0,
        "assessments": assessments,
    }
    _save(output / "reader-validation.summary.json", summary)
    return summary
