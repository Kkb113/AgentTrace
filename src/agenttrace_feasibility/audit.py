"""Conservative attribution from a live, authenticated Exchange audit capture.

The enrolled connector ID comes from Anthropic's published setup documentation.
This route uses a scoped unique Internet Message-ID join, not an assumed
equivalence between Exchange store IDs and Graph immutable IDs.
"""

from __future__ import annotations

from datetime import datetime

from .attribution import finding
from .validation import canonical_bytes, digest, timestamp

CLAUDE_CONNECTOR_APP_ID = "07c030f6-5743-41b7-ba00-0a6e85f37c17"
CONNECTOR_REFERENCE = (
    "https://support.claude.com/en/articles/12542951-set-up-the-microsoft-365-connector"
)


def _sender_matches(message: dict, mailbox: str) -> bool:
    address = message.get("from", {}).get("emailAddress", {}).get("address", "")
    if address.casefold() == mailbox.casefold():
        return True
    # Exchange can return a legacy DN; resolve only against this live item's MIME.
    return (
        address.casefold().startswith("/o=")
        and message.get("captured_mime_from_address", "").casefold() == mailbox.casefold()
    )


def assess_audit_capture(
    messages: list[dict],
    records: list[dict],
    *,
    tenant_id: str,
    mailbox: str,
    subject: str,
    sent_folder_id: str,
    first_seen: datetime,
    authenticated_live_capture: bool,
    complete: bool,
) -> dict:
    """Internal rule; only the live collector supplies authenticated provenance.

    Offline unit-test calls exercise semantics, not source authenticity. There is
    no command that upgrades an arbitrary JSON import to a live capture.
    """
    agent = finding("unknown", None, ["completed_scoped_agent_send_evidence_missing"])
    sent = [
        m
        for m in messages
        if m.get("subject") == subject
        and m.get("parentFolderId") == sent_folder_id
        and m.get("isDraft") is False
        and _sender_matches(m, mailbox)
    ]
    age = None
    matched: list[dict] = []
    if not authenticated_live_capture:
        agent = finding("unknown", None, ["capture_authenticity_not_established"])
    elif not complete:
        agent = finding("unknown", None, ["capture_incomplete_or_audit_pending"])
    elif len(sent) != 1:
        agent = finding("unknown", None, ["sent_item_missing_or_ambiguous"])
    elif sent[0].get("internetMessageId"):
        item = sent[0]
        for record in records:
            data = record.get("auditData", {})
            if not isinstance(data, dict):
                continue
            if (
                record.get("organizationId") == tenant_id
                and data.get("OrganizationId") == tenant_id
                and data.get("TokenTenantId") == tenant_id
                and data.get("MailboxOwnerUPN", "").casefold() == mailbox.casefold()
                and record.get("userPrincipalName", "").casefold() == mailbox.casefold()
                and record.get("operation") == "Send"
                and data.get("Operation") == "Send"
                and data.get("ResultStatus") == "Succeeded"
                and data.get("Item", {}).get("InternetMessageId") == item["internetMessageId"]
                and data.get("Item", {}).get("Subject") == subject
            ):
                matched.append(record)
        # Duplicate identical records are idempotent; contradictory records fail closed.
        unique = {canonical_bytes(r): r for r in matched}
        matched = list(unique.values())
        if len(matched) == 1:
            event = matched[0]
            data = event["auditData"]
            app_id = data.get("ClientAppId")
            context_app = data.get("AppAccessContext", {}).get("ClientAppId")
            event_time = timestamp(event["createdDateTime"])
            sent_time = timestamp(item["sentDateTime"])
            age = (first_seen - event_time).total_seconds()
            if (
                app_id == CLAUDE_CONNECTOR_APP_ID
                and context_app == app_id
                and data.get("ClientRequestId")
                and data.get("MailboxGuid")
                and data.get("Id") == event.get("id")
                and event.get("id")
                and age >= 0
                and abs((event_time - sent_time).total_seconds()) <= 2
            ):
                agent = finding(
                    "verified_agent",
                    True,
                    ["authenticated_exchange_send_for_enrolled_agent_connector"],
                    ["audit-record-sha256:" + digest(canonical_bytes(event))],
                )
            else:
                agent = finding("unknown", None, ["executor_or_event_consistency_unresolved"])
        elif len(matched) > 1:
            agent = finding("unknown", None, ["ambiguous_or_conflicting_send_events"])
    return {
        "findings": {
            "agent_send_attribution": agent,
            "content_assessment": finding(
                "unknown", None, ["statistical_content_experiment_not_run_by_evidence_spike"]
            ),
        },
        "supporting_observations": {
            "unique_sent_copy": len(sent) == 1,
            "matching_completed_send_events": len(matched),
            "join_basis": "authenticated_tenant_mailbox_unique_sent_copy_internet_message_id",
            "audit_to_graph_immutable_id_equivalence_established": False,
            "first_successful_collection_age_seconds": age,
            "availability_interpretation": "available_by_this_age_not_exact_ingestion_latency",
            "rule_scope": "enrolled_claude_connector_only_other_executors_remain_unknown",
        },
    }
