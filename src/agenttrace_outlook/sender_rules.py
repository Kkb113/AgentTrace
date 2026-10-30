"""Versioned sender rules. Observable clues and source execution are distinct from a receipt verdict."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Literal

from pydantic import Field, ValidationInfo, field_validator

from .agent_providers import AgentProvider, declaration_matches
from .contracts import Code, Observation, Opaque, Record

RULE_VERSION: Literal["sender-rules/unknown/v1"] = "sender-rules/unknown/v1"
CLAUDE_APP = "07c030f6-5743-41b7-ba00-0a6e85f37c17"
HUMAN_RULE: Literal["sender-rules/human/v3"] = "sender-rules/human/v3"
MCP_MARKER_RULE: Literal["sender-rules/known-mcp-marker-poc/v1"] = (
    "sender-rules/known-mcp-marker-poc/v1"
)
GMAIL_API_RULE: Literal["sender-rules/gmail-api-indicator-poc/v1"] = (
    "sender-rules/gmail-api-indicator-poc/v1"
)
AGENT_RULE: Literal["sender-rules/claude-corroborated/v1"] = "sender-rules/claude-corroborated/v1"
PROVIDER_RULE: Literal["sender-rules/provider-corroborated/v1"] = (
    "sender-rules/provider-corroborated/v1"
)
POLICY_VERSION = "corroborated-poc-human/v6"


class RuleAssessment(Record):
    rule_version: Literal[
        "sender-rules/unknown/v1",
        "sender-rules/human/v2",
        "sender-rules/human/v3",
        "sender-rules/human-capable/v1",
        "sender-rules/claude-corroborated/v1",
        "sender-rules/provider-corroborated/v1",
        "sender-rules/known-mcp-marker-poc/v1",
        "sender-rules/gmail-api-indicator-poc/v1",
    ] = RULE_VERSION
    category: Literal["Unknown", "Human", "AI Agent"] = "Unknown"
    inspection: Literal["complete", "incomplete", "conflicting"]
    human_candidate: bool
    human_support: Literal["supported_client_compatibility"] = "supported_client_compatibility"
    agent_execution: Literal[
        "unavailable", "verified_enrolled_send", "conflicting", "not_established"
    ]
    receipt_link: Literal[
        "unqualified", "missing", "conflicting", "corroborated_indicators", "header_indicator"
    ]
    reason_codes: tuple[Code, ...] = Field(min_length=1)
    evidence_refs: tuple[Opaque, ...] = ()

    @field_validator("category", mode="before")
    @classmethod
    def historical_label(cls, value: Any, info: ValidationInfo) -> Any:
        if (
            value == "Human-capable"
            and info.data.get("rule_version") == "sender-rules/human-capable/v1"
        ):
            return "Human"
        return value


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def enrolled_sender(snapshot: dict[str, Any], address: str) -> bool:
    rows = snapshot.get("internetMessageHeaders")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return False
    values = [r.get("value") for r in rows if str(r.get("name", "")).lower() == "from"]
    if len(values) != 1 or not isinstance(values[0], str):
        return False
    try:
        addresses = getaddresses(values)
        return len(addresses) == 1 and addresses[0][1].lower() == address.lower()
    except (ValueError, TypeError):
        return False


def inspect_snapshot(
    observation: Observation, snapshot: dict[str, Any] | None
) -> tuple[Literal["complete", "incomplete", "conflicting"], tuple[str, ...]]:
    if (
        not snapshot
        or sha(snapshot) != observation.source_digest
        or not observation.inspection_complete
    ):
        return "incomplete", ("message_inspection_incomplete",)
    rows = snapshot.get("internetMessageHeaders")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 500:
        return "incomplete", ("headers_missing_or_unsupported",)
    headers: dict[str, list[str]] = {}
    size = 0
    for row in rows:
        if (
            not isinstance(row, dict)
            or set(row) != {"name", "value"}
            or not all(isinstance(row[k], str) for k in row)
        ):
            return "incomplete", ("header_shape_invalid",)
        name, value = row["name"], row["value"]
        try:
            size += len(name.encode()) + len(value.encode())
        except UnicodeEncodeError:
            return "incomplete", ("header_encoding_invalid",)
        if (
            len(name) > 256
            or len(value) > 32768
            or size > 131072
            or not re.fullmatch(r"[!-9;-~]+", name)
            or "\x00" in value
            or "\r" in value.replace("\r\n", "\n")
            or re.search(r"\n(?![ \t])", value.replace("\r\n", "\n"))
        ):
            return "incomplete", ("header_bounds_invalid",)
        headers.setdefault(name.lower(), []).append(value)
    if any(not headers.get(key) for key in ("message-id", "from", "date")):
        return "incomplete", ("required_headers_missing",)
    if any(len(headers[key]) != 1 for key in ("message-id", "from", "date")):
        return "conflicting", ("required_header_missing_or_ambiguous",)
    if (
        not headers.get("received")
        or snapshot.get("isDraft") is not False
        or not snapshot.get("sentDateTime")
    ):
        return "incomplete", ("supported_fields_incomplete",)
    if headers["message-id"][0].strip() != snapshot.get("internetMessageId"):
        return "conflicting", ("message_id_fields_conflict",)
    try:
        if parsedate_to_datetime(headers["date"][0]).tzinfo is None:
            raise ValueError
        sender = getaddresses(headers["from"])
        if len(sender) != 1 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", sender[0][1]):
            raise ValueError
        for key in ("sentDateTime", "receivedDateTime"):
            if datetime.fromisoformat(snapshot[key]).tzinfo is None:
                raise ValueError
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        return "incomplete", ("supported_fields_invalid",)
    hints: set[str] = set()
    for name, values in headers.items():
        value = " ".join(values).lower()
        if name == "x-ai-generated" or name.startswith(("x-mcp", "x-agent")):
            hints.add("untrusted_agent_declaration")
        if name == "received" and "gmailapi.google.com" in value and "httprest" in value:
            hints.add("generic_api_submission")
        if name == "auto-submitted" and any(v.strip().lower() != "no" for v in values):
            hints.add("conventional_automation_indicator")
        if name in {
            "list-id",
            "list-unsubscribe",
            "x-auto-response-suppress",
            "x-autoreply",
            "x-autorespond",
        } or (
            name == "precedence"
            and any(v.strip().lower() in {"bulk", "list", "junk"} for v in values)
        ):
            hints.add("conventional_automation_indicator")
        if name in {"x-mailer", "user-agent"} and any(
            marker in value
            for marker in ("python", "curl/", "mcp", "power automate", "automation", "smtplib")
        ):
            hints.add("automation_client_indicator")
    return "complete", tuple(sorted(hints))


def evaluate(
    observation: Observation,
    snapshot: dict[str, Any] | None,
    source: dict[str, Any] | None,
    now: datetime,
    *,
    providers: tuple[AgentProvider, ...] = (),
    allow_known_mcp_marker: bool = False,
    allow_gmail_api_poc: bool = False,
) -> RuleAssessment:
    inspection, hints = inspect_snapshot(observation, snapshot)
    reasons = set(hints)
    human = inspection == "complete" and not hints
    if human:
        reasons.add("compatible_client_path_not_human_identity")
    execution: Literal[
        "unavailable", "verified_enrolled_send", "conflicting", "not_established"
    ] = "unavailable"
    link: Literal[
        "unqualified", "missing", "conflicting", "corroborated_indicators", "header_indicator"
    ] = "missing"
    refs: tuple[str, ...] = ()
    agent = False
    agent_rule: Literal[
        "sender-rules/claude-corroborated/v1",
        "sender-rules/provider-corroborated/v1",
        "sender-rules/known-mcp-marker-poc/v1",
        "sender-rules/gmail-api-indicator-poc/v1",
    ] = AGENT_RULE
    if source:
        refs = tuple(source.get("evidence_refs", ()))
        if (
            source.get("expires_at", 0) <= now.timestamp()
            or source.get("observed_version") != observation.source_version
        ):
            reasons.add("source_stale_or_version_mismatch")
            # A refresh is not contrary actor evidence. Preserve the explicitly
            # accepted clean-client interpretation across a routine audit wait;
            # stale positive/conflicting/error evidence still cannot authorize it.
            human = (
                human
                and source.get("observed_version") == observation.source_version
                and (
                    source.get("status") == "normal_client_context"
                    or source.get("reason") == "completed_send_evidence_missing"
                    or (
                        source.get("status") == "pending"
                        and source.get("reason") == "audit_search_pending"
                    )
                )
            )
        elif source.get("status") == "verified_enrolled_send":
            execution, link = "verified_enrolled_send", "unqualified"
            human = False
            reasons.add("authenticated_enrolled_agent_send_observed")
            reasons.add("received_copy_link_unqualified")
            declarations = [
                r["value"].strip().lower()
                for r in (
                    (snapshot or {}).get("internetMessageHeaders", [])
                    if inspection == "complete"
                    else []
                )
                if r.get("name", "").lower() == "x-ai-generated"
            ]
            provider = next(
                (p for p in providers if p.fingerprint == source.get("provider_fingerprint")),
                None,
            )
            provider_bound = (
                provider is not None
                and provider.evidence_ref in refs
                and source.get("provider_client_id") == str(provider.client_id)
            )
            legacy = (
                source.get("provider_fingerprint") is None
                and source.get("provider_client_id") is None
            )
            if not legacy and not provider_bound:
                reasons.add("enrolled_provider_pin_unavailable_or_changed")
            if (
                inspection == "complete"
                and (legacy or provider_bound)
                and declaration_matches(provider, declarations)
                and source.get("receipt_context") == "corroborated_scope_messageid_time"
            ):
                agent, link = True, "corroborated_indicators"
                reasons.discard("received_copy_link_unqualified")
                reasons.discard("untrusted_agent_declaration")
                reasons.add(
                    "enrolled_application_send_corroborated"
                    if provider_bound
                    else "known_mcp_marker_corroborated"
                )
                if provider_bound:
                    agent_rule = PROVIDER_RULE
                reasons.add("corroborated_poc_indicators_not_forensic_identity")
        elif source.get("status") == "conflicting":
            execution, link, human = "conflicting", "conflicting", False
            reasons.add("source_executor_or_identity_conflict")
        elif (
            source.get("status") in {"pending", "normal_client_context"}
            or source.get("reason") == "completed_send_evidence_missing"
        ):
            execution = "not_established"
            reasons.add("compatible_path_does_not_establish_controller")
        else:
            execution = "not_established"
            reasons.add(str(source.get("reason", "completed_send_evidence_missing")))
            if source.get("reason") != "sender_source_not_enrolled_for_message":
                human = False
    else:
        reasons.add("authenticated_send_source_unavailable")
    indicator_conflict = bool(source) and (
        (source or {}).get("status") in {"conflicting", "normal_client_context"}
        or (source or {}).get("observed_version") != observation.source_version
        or (
            (source or {}).get("status") == "verified_enrolled_send"
            and (source or {}).get("expires_at", 0) > now.timestamp()
        )
    )
    if (
        allow_known_mcp_marker
        and not agent
        and inspection == "complete"
        and hints == ("untrusted_agent_declaration",)
        and not indicator_conflict
    ):
        declarations = [
            row["value"].strip().lower()
            for row in (snapshot or {}).get("internetMessageHeaders", [])
            if row.get("name", "").lower() == "x-ai-generated"
        ]
        if declarations == ["mcp-office365"]:
            agent, human, link, agent_rule = True, False, "header_indicator", MCP_MARKER_RULE
            reasons = {"known_mcp_marker_poc_indicator_spoofable"}
            refs = ("header-sha256:" + sha({"x-ai-generated": declarations[0]}),)
    if (
        allow_gmail_api_poc
        and not agent
        and inspection == "complete"
        and hints == ("generic_api_submission",)
        and not indicator_conflict
    ):
        hops = sorted(
            {
                row["value"]
                for row in (snapshot or {}).get("internetMessageHeaders", [])
                if row.get("name", "").lower() == "received"
                and "gmailapi.google.com" in row["value"].lower()
                and "httprest" in row["value"].lower()
            }
        )
        if len(hops) == 1:
            agent, human, link, agent_rule = True, False, "header_indicator", GMAIL_API_RULE
            reasons = {"generic_api_submission", "gmail_api_poc_indicator_not_agent_specific"}
            refs = ("transport-sha256:" + sha(hops[0]),)
    if observation.observed_at + timedelta(hours=24) < now:
        reasons.add("late_observation_window_closed")
    elif observation.observed_at + timedelta(hours=2) <= now:
        reasons.add("initial_evidence_window_closed")
    if not human:
        reasons.discard("compatible_client_path_not_human_identity")
    return RuleAssessment(
        rule_version=agent_rule if agent else HUMAN_RULE if human else RULE_VERSION,
        category="AI Agent" if agent else "Human" if human else "Unknown",
        inspection=inspection,
        human_candidate=human,
        agent_execution=execution,
        receipt_link=link,
        reason_codes=tuple(sorted(reasons)),
        evidence_refs=refs,
    )


def qualify_exchange_send(
    records: list[dict[str, Any]],
    *,
    tenant: str,
    mailbox: str,
    mailbox_guid: str,
    message_id: str,
    sent_at: datetime,
    publisher_current: bool,
    client_id: str = CLAUDE_APP,
) -> tuple[str, str, tuple[str, ...]]:
    """Source semantics only. This does not bind an audit item to a received copy."""
    if not publisher_current:
        return "not_established", "publisher_unavailable_or_revoked", ()
    relevant: dict[str, dict[str, Any]] = {}
    for record in records:
        data = record.get("auditData")
        if not isinstance(data, dict):
            return "conflicting", "audit_shape_invalid", ()
        if not isinstance(data.get("Item"), dict) or not isinstance(
            data.get("AppAccessContext", {}), dict
        ):
            return "conflicting", "audit_shape_invalid", ()
        if data.get("Item", {}).get("InternetMessageId") != message_id:
            continue
        key = str(record.get("id", ""))
        if not key or (key in relevant and relevant[key] != record):
            return "conflicting", "audit_record_identity_conflict", ()
        relevant[key] = record
    if len(relevant) != 1:
        return (
            ("conflicting", "multiple_send_records", ())
            if relevant
            else ("not_established", "completed_send_evidence_missing", ())
        )
    record = next(iter(relevant.values()))
    data = record["auditData"]
    if (
        not all(
            isinstance(data.get(key), str)
            for key in (
                "OrganizationId",
                "TokenTenantId",
                "MailboxOwnerUPN",
                "MailboxGuid",
                "Operation",
                "Workload",
                "ResultStatus",
                "Id",
            )
        )
        or not isinstance(record.get("userPrincipalName"), str)
        or not isinstance(data.get("Item", {}).get("Id"), str)
    ):
        return "conflicting", "audit_shape_invalid", ()
    try:
        occurred = datetime.fromisoformat(record["createdDateTime"])
        inner = datetime.fromisoformat(data["CreationTime"])
        common = (
            record.get("organizationId")
            == tenant
            == data.get("OrganizationId")
            == data.get("TokenTenantId")
            and record.get("userPrincipalName", "").lower()
            == mailbox.lower()
            == data.get("MailboxOwnerUPN", "").lower()
            and data.get("MailboxGuid", "").lower() == mailbox_guid.lower()
            and record.get("operation") == data.get("Operation") == "Send"
            and data.get("Workload") == "Exchange"
            and data.get("ResultStatus") == "Succeeded"
            and record.get("id") == data.get("Id")
            and bool(data.get("Item", {}).get("Id"))
            and occurred.tzinfo is not None
            and inner.tzinfo is not None
            and abs((occurred - sent_at).total_seconds()) <= 2
            and abs((occurred - inner).total_seconds()) <= 2
        )
    except (ValueError, TypeError, KeyError, OverflowError):
        common = False
    ref = "audit-sha256:" + sha(record)
    if (
        common
        and data.get("ClientAppId") != client_id
        and str(data.get("ClientInfoString", "")).split(";")[0].lower()
        in {"client=owa", "client=outlook", "client=outlookservice", "client=msexchangerpc"}
    ):
        return "normal_client_context", "browser_or_normal_client_context", (ref,)
    valid = (
        common
        and data.get("ClientAppId")
        == data.get("AppAccessContext", {}).get("ClientAppId")
        == client_id
        and isinstance(data.get("ClientRequestId"), str)
        and 1 <= len(data["ClientRequestId"]) <= 2048
    )
    return (
        ("verified_enrolled_send", "authenticated_enrolled_agent_send_observed", (ref,))
        if valid
        else ("conflicting", "audit_executor_or_scope_unresolved", (ref,))
    )


def corroborated_copy_context(
    observation: Observation,
    snapshot: dict[str, Any],
    rows: list[dict[str, Any]],
    sent_folder: str,
) -> bool:
    """Shared live/replay copy checks; contradictory repeated provider IDs reject."""
    copies: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row.get("id")
        if (
            not isinstance(key, str)
            or not key
            or row.get("internetMessageId") != snapshot.get("internetMessageId")
            or not isinstance(row.get("parentFolderId"), str)
            or (key in copies and copies[key] != row)
        ):
            return False
        copies[key] = row
    sent = [r for r in copies.values() if r["parentFolderId"] == sent_folder]
    received = [r for r in copies.values() if r["parentFolderId"] != sent_folder]
    return (
        len(copies) == 2
        and len(sent) == len(received) == 1
        and received[0]["id"] == observation.message_id
        and all(
            r.get("isDraft") is False and r.get("sentDateTime") == snapshot.get("sentDateTime")
            for r in copies.values()
        )
    )
