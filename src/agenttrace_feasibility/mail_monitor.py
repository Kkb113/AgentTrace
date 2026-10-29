"""Operator-only metadata demo with isolated experimental binary header predictions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit
from uuid import UUID

from agenttrace_foundation.authorization import AccessDenied
from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.contracts import IngestionError
from agenttrace_ingestion.transport import MicrosoftTransport

from .audit import CLAUDE_CONNECTOR_APP_ID, assess_audit_capture
from .capabilities import azure_cli_prefix
from .validation import InputError, load_json, timestamp

ROOT = Path(__file__).resolve().parents[2]
GRAPH = "https://graph.microsoft.com/v1.0"
PREFER = {"Prefer": 'IdType="ImmutableId"'}
FIELDS = (
    "id,subject,from,sender,receivedDateTime,sentDateTime,parentFolderId,isDraft,internetMessageId"
)
MAX_MESSAGES = 10_000
VISIBLE_HEADERS = {
    "received",
    "from",
    "sender",
    "reply-to",
    "return-path",
    "message-id",
    "date",
    "authentication-results",
    "arc-authentication-results",
    "received-spf",
    "x-mailer",
    "user-agent",
    "auto-submitted",
    "precedence",
    "list-id",
}


def safe(value: object, limit: int = 500) -> str:
    """Prevent terminal escape, bidi, CR and newline injection from untrusted mail."""
    text = str(value)
    text = "".join(
        f"\\u{ord(c):04x}" if unicodedata.category(c).startswith("C") else c for c in text
    )
    return text[:limit] + ("... [truncated]" if len(text) > limit else "")


def address(message: dict) -> str:
    raw = str(message.get("from", {}).get("emailAddress", {}).get("address", ""))
    return (
        str(message.get("captured_mime_from_address", raw))
        if raw.casefold().startswith("/o=")
        else raw
    )


def header_rows(message: dict, *, all_headers: bool = False) -> list[dict]:
    rows = message.get("internetMessageHeaders", [])
    if not isinstance(rows, list) or len(rows) > 500:
        raise IngestionError("header_count_or_shape_invalid")
    result, size = [], 0
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(k), str) for k in ("name", "value")
        ):
            raise IngestionError("header_shape_invalid")
        name, value = row["name"], row["value"]
        size += len(name.encode()) + len(value.encode())
        if size > 131_072 or len(name) > 256:
            raise IngestionError("header_size_limit")
        lower = name.casefold()
        if (
            all_headers
            or lower in VISIBLE_HEADERS
            or "agent" in lower
            or "claude" in lower
            or lower.startswith("x-ai")
        ):
            result.append(
                {
                    "name": safe(name, 256),
                    "value": safe(value, 2000),
                    "trust": "received_header_not_executor_proof",
                }
            )
    return result


def initial_result(
    message: dict, mailbox: str, *, all_headers: bool = False, demo_heuristic: bool = False
) -> dict:
    own_sender = address(message).casefold() == mailbox.casefold()
    headers = header_rows(message, all_headers=all_headers)
    api_hints = [
        row
        for row in headers
        if row["name"].casefold() == "received"
        and re.search(r"\bgmailapi\.google\.com\b", row["value"], re.I)
        and re.search(r"\bwith\s+HTTPREST\b", row["value"], re.I)
    ]
    office_hints = [
        row
        for row in headers
        if row["name"].casefold() == "x-ai-generated"
        and row["value"].strip().casefold() == "mcp-office365"
    ]
    submission_hints = []
    if office_hints:
        submission_hints.append("Office365 MCP declaration: x-ai-generated: mcp-office365")
    if api_hints:
        submission_hints.append("Gmail API submission indicated (unverified header)")
    result = {
        "event": "message",
        "observed_at": datetime.now(UTC).isoformat(),
        "message_ref": message["id"],
        "sender": safe(address(message)),
        "subject": safe(message.get("subject", "")),
        "received_utc": safe(message.get("receivedDateTime", "")),
        "internet_message_id": safe(message.get("internetMessageId", "")),
        "classification": "Unable to determine",
        "qualification": "insufficient_evidence",
        "submission_hint": "; ".join(submission_hints) or "No recognized agent submission marker",
        "evidence": [
            "Authenticated read of receiving Microsoft mailbox; no message body requested.",
            "Sender-side Exchange evidence pending."
            if own_sender
            else "External sender: receiving-mailbox access does not expose its send execution logs.",
            "Headers, authentication passes and missing AI markers cannot prove human or AI execution.",
        ],
        "headers": headers,
    }
    if demo_heuristic:
        result["classification"] = (
            "Sent by AI Agent" if api_hints or office_hints else "Sent by Human"
        )
        result["qualification"] = "experimental_header_heuristic"
        result["evidence"].insert(
            0,
            "Demo rule: x-ai-generated: mcp-office365 observed. This is a sender declaration; the header alone is not authenticated execution evidence."
            if office_hints
            else (
                "Demo rule: Gmail API Received/HTTPREST marker observed. This is a heuristic; non-AI applications can use the same API and headers can be forged."
                if api_hints
                else "Demo rule: no recognized agent marker; Human is the binary demo prediction, not verified human-action evidence."
            ),
        )
    return result


class MailSource:
    """Only GETs inside the configured mailbox; reject cross-scope pagination."""

    def __init__(self, transport, mailbox_id: str):
        UUID(mailbox_id)
        self.transport = transport
        self.base = GRAPH + "/users/" + quote(mailbox_id, safe="")
        self.excluded: set[str] = set()
        self.sent_folder = ""

    def get(self, url: str) -> dict:
        parsed = urlsplit(url)
        prefix = urlsplit(self.base).path
        route = parsed.path.removeprefix(prefix)
        allowed = parsed.path.startswith(prefix) and re.fullmatch(
            r"/messages(?:/[^/]+)?|/mailFolders/(?:sentitems|drafts|outbox)(?:/messages)?", route
        )
        params = parse_qs(parsed.query, keep_blank_values=True)
        allowed_params = {"$select", "$filter", "$orderby", "$top", "$skip", "$skiptoken"}
        selections = params.get("$select", [""])
        permitted_fields = set(FIELDS.split(",")) | {"internetMessageHeaders"}
        if (
            not allowed
            or parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.fragment
            or set(params) - allowed_params
            or any(len(values) != 1 for values in params.values())
            or not selections[0]
            or not set(selections[0].split(",")) <= permitted_fields
        ):
            raise IngestionError("demo_mail_route_out_of_scope")
        return self.transport.request("GET", url, headers=PREFER)

    def pages(self, url: str, *, maximum: int = MAX_MESSAGES) -> list[dict]:
        rows, visited = [], set()
        while url:
            if url in visited or len(visited) >= 100:
                raise IngestionError("demo_pagination_limit_or_cycle")
            visited.add(url)
            page = self.get(url)
            values = page.get("value")
            if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
                raise IngestionError("demo_page_shape_invalid")
            rows.extend(values)
            if len(rows) > maximum:
                raise IngestionError("demo_message_limit_restart_required")
            url = page.get("@odata.nextLink", "")
            if not isinstance(url, str):
                raise IngestionError("demo_next_link_invalid")
        return rows

    def prepare(self) -> None:
        for name in ("sentitems", "drafts", "outbox"):
            folder = self.get(self.base + "/mailFolders/" + name + "?$select=id")
            if not isinstance(folder.get("id"), str) or not folder["id"]:
                raise IngestionError("demo_folder_identity_missing")
            self.excluded.add(folder["id"])
            if name == "sentitems":
                self.sent_folder = folder["id"]

    def incoming(self, since: datetime, until: datetime) -> list[dict]:
        query = urlencode(
            {
                "$filter": f"receivedDateTime ge {since.isoformat()} and receivedDateTime le {until.isoformat()}",
                "$orderby": "receivedDateTime asc",
                "$select": FIELDS,
                "$top": "100",
            }
        )
        rows = self.pages(self.base + "/messages?" + query)
        return [
            m
            for m in rows
            if m.get("isDraft") is False and m.get("parentFolderId") not in self.excluded
        ]

    def detail(self, message: dict) -> dict:
        detail = self.get(
            self.base
            + "/messages/"
            + quote(message["id"], safe="")
            + "?"
            + urlencode({"$select": FIELDS + ",internetMessageHeaders"})
        )
        if address(detail).casefold().startswith("/o="):
            from_values = [
                h["value"]
                for h in detail.get("internetMessageHeaders", [])
                if h.get("name", "").casefold() == "from"
            ]
            if len(from_values) == 1:
                detail["captured_mime_from_address"] = parseaddr(from_values[0])[1]
        return detail

    def sent_copies(self, message: dict) -> list[dict]:
        mid = message.get("internetMessageId")
        if not isinstance(mid, str) or not mid:
            return []
        query = urlencode(
            {
                "$filter": "internetMessageId eq '" + mid.replace("'", "''") + "'",
                "$select": FIELDS + ",internetMessageHeaders",
                "$top": "100",
            }
        )
        copies = self.pages(self.base + "/mailFolders/sentitems/messages?" + query)
        for item in copies:
            if address(item).casefold().startswith("/o="):
                detail = self.detail(item)
                if address(detail) and not address(detail).casefold().startswith("/o="):
                    item["captured_mime_from_address"] = address(detail)
                    continue
                from_values = [
                    h["value"]
                    for h in item.get(
                        "internetMessageHeaders", detail.get("internetMessageHeaders", [])
                    )
                    if h.get("name", "").casefold() == "from"
                ]
                if len(from_values) == 1:
                    item["captured_mime_from_address"] = parseaddr(from_values[0])[1]
        return copies


@dataclass
class AuditJob:
    message: dict
    result: dict
    created: datetime
    next_check: float = 0
    query_id: str | None = None


class ExchangeEvidence:
    """Poll analytical search jobs, never email send APIs; Gmail senders are ineligible."""

    def __init__(self, mail: MailSource, audit, settings: dict):
        self.mail, self.audit, self.settings = mail, audit, settings
        self.root = GRAPH + "/security/auditLog/queries"

    def eligible(self, message: dict) -> bool:
        return address(message).casefold() == self.settings["mailbox"].casefold()

    def step(self, job: AuditJob, now: datetime) -> dict | None:
        if now - job.created > timedelta(hours=2):
            return {
                **job.result,
                "event": "audit_update",
                "evidence": [
                    "Two-hour demo audit wait expired without a qualified verdict; absence is not human proof."
                ],
            }
        if job.query_id is None:
            sent = timestamp(job.message["sentDateTime"])
            query = self.audit.request(
                "POST",
                self.root,
                body={
                    "displayName": "AgentTrace live read-only sender demonstration",
                    "filterStartDateTime": (sent - timedelta(minutes=2)).isoformat(),
                    "filterEndDateTime": (sent + timedelta(minutes=2)).isoformat(),
                    "recordTypeFilters": ["exchangeItem"],
                    "operationFilters": ["Send"],
                    "userPrincipalNameFilters": [self.settings["mailbox"]],
                },
            )
            if not isinstance(query.get("id"), str) or not query["id"]:
                raise IngestionError("demo_audit_query_id_missing")
            job.query_id = query["id"]
            job.next_check = time.monotonic() + 30
            return None
        url = self.root + "/" + quote(job.query_id, safe="")
        state = self.audit.request("GET", url)
        if state.get("status") in {"failed", "cancelled"}:
            raise IngestionError("demo_audit_query_failed")
        if state.get("status") != "succeeded":
            job.next_check = time.monotonic() + 30
            return None
        records, page_url, visited = [], url + "/records?$top=100", set()
        while page_url:
            parsed = urlsplit(page_url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != "graph.microsoft.com"
                or parsed.path != urlsplit(url).path + "/records"
                or parsed.fragment
                or page_url in visited
                or len(visited) >= 20
            ):
                raise IngestionError("demo_audit_pagination_out_of_scope")
            visited.add(page_url)
            page = self.audit.request("GET", page_url)
            values = page.get("value")
            if not isinstance(values, list):
                raise IngestionError("demo_audit_page_invalid")
            for record in values:
                data = record.get("auditData", {})
                if isinstance(data, str):
                    data = json.loads(data)
                if data.get("Item", {}).get("InternetMessageId") == job.message.get(
                    "internetMessageId"
                ):
                    records.append({**record, "auditData": data})
            page_url = page.get("@odata.nextLink", "")
            if not isinstance(page_url, str):
                raise IngestionError("demo_audit_page_invalid")
        copies = self.mail.sent_copies(job.message)
        # This demo supports only the enrolled own-mailbox copy pair; reject
        # inconsistent received metadata before invoking the original sender rule.
        if len(copies) != 1 or any(
            copies[0].get(key) != job.message.get(key) for key in ("internetMessageId", "subject")
        ):
            job.next_check = time.monotonic() + 300
            return None
        if timestamp(copies[0]["sentDateTime"]) != timestamp(job.message["sentDateTime"]):
            job.next_check = time.monotonic() + 300
            return None
        result = assess_audit_capture(
            copies,
            records,
            tenant_id=self.settings["tenant"],
            mailbox=self.settings["mailbox"],
            subject=job.message["subject"],
            sent_folder_id=self.mail.sent_folder,
            first_seen=now,
            authenticated_live_capture=True,
            complete=True,
        )["findings"]["agent_send_attribution"]
        if result["flagged"] is True:
            return {
                **job.result,
                "event": "audit_update",
                "observed_at": now.isoformat(),
                "classification": "Sent by AI Agent",
                "qualification": "authenticated_enrolled_exchange_rule",
                "evidence": [
                    "Authenticated successful Exchange Send for enrolled Claude connector.",
                    "Unique scoped Sent Items copy linked by exact Internet Message-ID; incoming copy has the same ID.",
                    "Narrow enrolled-connector rule; sender/recipient immutable-ID equivalence is not asserted.",
                    *result["evidence_refs"],
                ],
            }
        # A completed search can precede audit ingestion; use a fresh bounded search later.
        job.query_id = None
        job.next_check = time.monotonic() + 300
        return None


def verify_publisher(settings: dict) -> bool:
    query = urlencode(
        {
            "$filter": "appId eq '" + CLAUDE_CONNECTOR_APP_ID + "'",
            "$select": "appId,verifiedPublisher",
        }
    )
    result = subprocess.run(
        [
            *azure_cli_prefix(),
            "rest",
            "--method",
            "get",
            "--url",
            GRAPH + "/servicePrincipals?" + query,
            "--subscription",
            settings["subscription"],
            "--only-show-errors",
            "-o",
            "json",
        ],
        capture_output=True,
        text=True,
        timeout=45,
        shell=False,
    )
    if result.returncode:
        return False
    rows = json.loads(result.stdout).get("value", [])
    return (
        len(rows) == 1
        and rows[0].get("appId") == CLAUDE_CONNECTOR_APP_ID
        and bool(rows[0].get("verifiedPublisher", {}).get("verifiedPublisherId"))
    )


def build_sources(directory: Path, *, exchange_audit: bool):
    settings = load_json(directory / "sandbox-settings.private.json")
    identities = load_json(directory / "workload-identities.private.json")
    for field in ("tenant", "mailbox_id"):
        UUID(settings[field])
    if not isinstance(settings.get("mailbox"), str) or not re.fullmatch(
        r"[^\s@]+@[^\s@]+", settings["mailbox"]
    ):
        raise InputError("demo_mailbox_configuration_invalid")

    def transport(alias):
        identity = identities[alias]
        provider = CertificateTokenProvider(
            settings["tenant"],
            identity["application"]["appId"],
            identity["certificate"]["thumbprint"],
            ROOT / "scripts/manage-workload-certificate.ps1",
        )
        return MicrosoftTransport(
            lambda *, force_refresh=False: provider.token(
                "https://graph.microsoft.com", force_refresh=force_refresh
            )
        )

    mail = MailSource(transport("mail-collector"), settings["mailbox_id"])
    evidence = None
    if exchange_audit:
        try:
            if verify_publisher(settings):
                evidence = ExchangeEvidence(mail, transport("audit-collector"), settings)
        except (AccessDenied, OSError, ValueError, subprocess.SubprocessError):
            # Optional audit failure must not prevent metadata monitoring.
            evidence = None
    return settings, mail, evidence


class Monitor:
    def __init__(
        self,
        mail: MailSource,
        mailbox: str,
        emit,
        *,
        audit=None,
        all_headers=False,
        demo_heuristic=False,
    ):
        self.mail, self.mailbox, self.emit = mail, mailbox, emit
        self.audit, self.all_headers = audit, all_headers
        self.demo_heuristic = demo_heuristic
        self.seen: set[str] = set()
        self.jobs: dict[str, AuditJob] = {}

    def cycle(self, since: datetime, now: datetime) -> int:
        count = 0
        for item in self.mail.incoming(since, now):
            ref = item.get("id")
            if not isinstance(ref, str) or not ref:
                raise IngestionError("demo_message_id_missing")
            if ref in self.seen:
                continue
            if len(self.seen) >= MAX_MESSAGES:
                raise IngestionError("demo_message_limit_restart_required")
            try:
                message = self.mail.detail(item)
                if message.get("id") != ref:
                    raise IngestionError("demo_message_identity_mismatch")
                result = initial_result(
                    message,
                    self.mailbox,
                    all_headers=self.all_headers,
                    demo_heuristic=self.demo_heuristic,
                )
            except IngestionError as error:
                if error.code == "source_item_not_found":
                    self.emit(
                        {
                            "event": "coverage_gap",
                            "reason": "Message disappeared before headers could be read; retrying if it reappears.",
                        }
                    )
                    continue
                raise
            if self.audit and self.audit.eligible(message):
                if len(self.jobs) >= 100:
                    result["evidence"].append(
                        "Audit backlog limit reached; no source verdict available."
                    )
                else:
                    self.jobs[ref] = AuditJob(message, result, now)
            elif address(message).casefold() == self.mailbox.casefold():
                result["evidence"][1] = (
                    "Exchange send evidence is disabled or publisher verification is unavailable."
                )
            self.emit(result)
            self.seen.add(ref)
            count += 1
        # At most one bounded audit task per cycle; messages are printed first.
        for ref, job in list(self.jobs.items()):
            if job.next_check > time.monotonic():
                continue
            try:
                update = self.audit.step(job, now)
                if update:
                    self.emit(update)
                    del self.jobs[ref]
            except (IngestionError, AccessDenied, ValueError, KeyError, TypeError, AttributeError):
                self.emit(
                    {
                        "event": "audit_status",
                        "reason": "Send evidence unavailable; no verdict upgrade. Retrying in five minutes.",
                    }
                )
                job.query_id = None
                job.next_check = time.monotonic() + 300
            break
        return count


def display(event: dict, *, json_output=False) -> None:
    if json_output:
        print(json.dumps(event, ensure_ascii=True), flush=True)
        return
    if event["event"] not in {"message", "audit_update"}:
        print("[" + event["event"].upper() + "] " + safe(event.get("reason", ""), 2000), flush=True)
        return
    print("\n" + "=" * 88)
    print("UPDATE" if event["event"] == "audit_update" else "NEW INCOMING EMAIL")
    for label, key in (
        ("From", "sender"),
        ("Subject", "subject"),
        ("Received UTC", "received_utc"),
        ("Classification", "classification"),
        ("Message-ID", "internet_message_id"),
    ):
        print(f"{label:16}: {safe(event[key], 500)}")
    print("Detection evidence:")
    print("  Submission hint: " + safe(event.get("submission_hint", "Not assessed")))
    print("  API hints are not proof of an AI agent; absence is not human proof.")
    for reason in event["evidence"]:
        print("  - " + safe(reason, 1000))
    print("Received headers (unverified as actor evidence):")
    for row in event["headers"]:
        print("  " + safe(row["name"], 256) + ": " + safe(row["value"], 2000))
    if not event["headers"]:
        print("  No selected headers available.")
    sys.stdout.flush()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings-directory", type=Path, default=ROOT / "work/private/secure-access"
    )
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=0,
        help="Include recent existing mail; default is new arrivals only.",
    )
    parser.add_argument(
        "--exchange-audit",
        action="store_true",
        help="Enable the existing narrow Microsoft/Claude audit route for own-mailbox senders only.",
    )
    parser.add_argument("--all-headers", action="store_true")
    parser.add_argument(
        "--demo-heuristic",
        action="store_true",
        help="Use the experimental Gmail API header rule for this terminal demo; not qualified actor attribution.",
    )
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument(
        "--once", action="store_true", help="One bounded read cycle for connectivity checks."
    )
    args = parser.parse_args(argv)
    if not 5 <= args.interval <= 300 or not 0 <= args.lookback_minutes <= 1440:
        parser.error("interval must be 5..300 seconds and lookback 0..1440 minutes")

    def emit(event):
        display(event, json_output=args.json_output)

    try:
        since = datetime.now(UTC) - timedelta(minutes=args.lookback_minutes)
        settings, mail, audit = build_sources(
            args.settings_directory, exchange_audit=args.exchange_audit
        )
        mail.prepare()
        emit(
            {
                "event": "ready",
                "reason": f"Monitoring {settings['mailbox']} across receiving folders (excluding Sent Items, Drafts, Outbox). Metadata/headers only; no bodies or mailbox writes. Ctrl+C stops. Start UTC: {since.isoformat()}.",
            }
        )
        emit(
            {
                "event": "policy",
                "reason": "Binary terminal demo: Gmail API traces or x-ai-generated: mcp-office365 map to Sent by AI Agent; other messages map to Sent by Human. Both are experimental header predictions, not verified actor evidence."
                if args.demo_heuristic
                else "AI Agent requires authenticated send evidence; Human requires a qualified human-action source (not configured). Headers alone yield Unable to determine. External Gmail send logs are not available through Outlook. No simulated labels.",
            }
        )
        emit(
            {
                "event": "audit_status",
                "reason": "Own-mailbox Claude audit reassessment enabled; source delays may be many minutes."
                if audit
                else "Exchange audit reassessment disabled/unavailable; use --exchange-audit for the enrolled own-mailbox route.",
            }
        )
        monitor = Monitor(
            mail,
            settings["mailbox"],
            emit,
            audit=audit,
            all_headers=args.all_headers,
            demo_heuristic=args.demo_heuristic,
        )
        heartbeat, failures = time.monotonic(), 0
        while True:
            now = datetime.now(UTC)
            delay = args.interval
            try:
                count = monitor.cycle(since, now)
                failures = 0
                if args.once or time.monotonic() - heartbeat >= 60:
                    emit(
                        {
                            "event": "heartbeat",
                            "reason": f"Read succeeded. New this cycle: {count}; observed: {len(monitor.seen)}; audit pending: {len(monitor.jobs)}. Waiting for incoming mail.",
                        }
                    )
                    heartbeat = time.monotonic()
            except IngestionError as error:
                if not error.retryable or args.once:
                    raise
                failures += 1
                delay = max(args.interval, error.retry_after, min(300, 2 ** min(failures, 8)))
                emit(
                    {
                        "event": "retry",
                        "reason": f"{error.code}; retrying in {delay}s. No human/AI assumption and no scan checkpoint advanced.",
                    }
                )
            if args.once:
                return 0
            time.sleep(delay)
    except KeyboardInterrupt:
        emit({"event": "stopped", "reason": "Stopped by operator. No emails were changed."})
        return 0
    except (
        AccessDenied,
        IngestionError,
        InputError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        subprocess.SubprocessError,
    ) as error:
        code = (
            error.code
            if isinstance(error, IngestionError)
            else "demo_configuration_or_source_unavailable"
        )
        emit(
            {
                "event": "error",
                "reason": code
                + "; no result fabricated. Check the existing reader configuration, access and connectivity.",
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
