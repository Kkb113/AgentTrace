"""Versioned sender rules. Observable clues and source execution are distinct from a receipt verdict."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Literal

from pydantic import Field

from .contracts import Code, Observation, Opaque, Record

RULE_VERSION: Literal["sender-rules/unknown/v1"] = "sender-rules/unknown/v1"
CLAUDE_APP = "07c030f6-5743-41b7-ba00-0a6e85f37c17"
HUMAN_CAPABLE_RULE: Literal["sender-rules/human-capable/v1"] = "sender-rules/human-capable/v1"
AGENT_RULE: Literal["sender-rules/claude-corroborated/v1"] = "sender-rules/claude-corroborated/v1"
POLICY_VERSION = "corroborated-poc-human-capable/v1"


class RuleAssessment(Record):
    rule_version: Literal[
        "sender-rules/unknown/v1",
        "sender-rules/human-capable/v1",
        "sender-rules/claude-corroborated/v1",
    ] = RULE_VERSION
    category: Literal["Unknown", "Human-capable", "AI Agent"] = "Unknown"
    inspection: Literal["complete", "incomplete", "conflicting"]
    human_candidate: bool
    human_support: Literal["supported_client_compatibility"] = "supported_client_compatibility"
    agent_execution: Literal[
        "unavailable", "verified_enrolled_send", "conflicting", "not_established"
    ]
    receipt_link: Literal["unqualified", "missing", "conflicting", "corroborated_indicators"]
    reason_codes: tuple[Code, ...] = Field(min_length=1)
    evidence_refs: tuple[Opaque, ...] = ()


def sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


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
        size += len(name.encode()) + len(value.encode())
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
) -> RuleAssessment:
    inspection, hints = inspect_snapshot(observation, snapshot)
    reasons = set(hints)
    human = inspection == "complete" and not hints
    if human:
        reasons.add("compatible_client_path_not_human_identity")
    execution: Literal[
        "unavailable", "verified_enrolled_send", "conflicting", "not_established"
    ] = "unavailable"
    link: Literal["unqualified", "missing", "conflicting", "corroborated_indicators"] = "missing"
    refs: tuple[str, ...] = ()
    agent = False
    if source:
        refs = tuple(source.get("evidence_refs", ()))
        if (
            source.get("expires_at", 0) <= now.timestamp()
            or source.get("observed_version") != observation.source_version
        ):
            reasons.add("source_stale_or_version_mismatch")
            human = False
        elif source.get("status") == "verified_enrolled_send":
            execution, link = "verified_enrolled_send", "unqualified"
            human = False
            reasons.add("authenticated_enrolled_agent_send_observed")
            reasons.add("received_copy_link_unqualified")
            declarations = [
                r["value"].strip().lower()
                for r in (snapshot or {}).get("internetMessageHeaders", [])
                if r.get("name", "").lower() == "x-ai-generated"
            ]
            if (
                inspection == "complete"
                and declarations == ["mcp-office365"]
                and source.get("receipt_context") == "corroborated_scope_messageid_time"
            ):
                agent, link = True, "corroborated_indicators"
                reasons.discard("received_copy_link_unqualified")
                reasons.discard("untrusted_agent_declaration")
                reasons.add("known_mcp_marker_corroborated")
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
    if observation.observed_at + timedelta(hours=24) < now:
        reasons.add("late_observation_window_closed")
    elif observation.observed_at + timedelta(hours=2) <= now:
        reasons.add("initial_evidence_window_closed")
    return RuleAssessment(
        rule_version=AGENT_RULE if agent else HUMAN_CAPABLE_RULE if human else RULE_VERSION,
        category="AI Agent" if agent else "Human-capable" if human else "Unknown",
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
        and data.get("ClientAppId") != CLAUDE_APP
        and str(data.get("ClientInfoString", "")).split(";")[0].lower()
        in {"client=owa", "client=outlook", "client=outlookservice", "client=msexchangerpc"}
    ):
        return "normal_client_context", "browser_or_normal_client_context", (ref,)
    valid = (
        common
        and data.get("ClientAppId")
        == data.get("AppAccessContext", {}).get("ClientAppId")
        == CLAUDE_APP
        and isinstance(data.get("ClientRequestId"), str)
        and 1 <= len(data["ClientRequestId"]) <= 2048
    )
    return (
        ("verified_enrolled_send", "authenticated_enrolled_agent_send_observed", (ref,))
        if valid
        else ("conflicting", "audit_executor_or_scope_unresolved", (ref,))
    )
