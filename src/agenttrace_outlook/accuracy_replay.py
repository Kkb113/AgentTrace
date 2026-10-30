"""Label-blind replay of the same pure evidence checks used by the live monitor."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .accuracy_contracts import DetectorPacket, Enrollment, Frame
from .agent_providers import provider_for_send
from .sender_rules import (
    CLAUDE_APP,
    RuleAssessment,
    corroborated_copy_context,
    enrolled_sender,
    evaluate,
    qualify_exchange_send,
    sha,
)

SNAPSHOT_FIELDS = {
    "isDraft",
    "internetMessageId",
    "sentDateTime",
    "receivedDateTime",
    "internetMessageHeaders",
}


def replay(packet: DetectorPacket, enrollment: Enrollment | None, at: datetime) -> RuleAssessment:
    """No case names, labels, reviewers, group IDs, paths, text or current categories."""
    frames = [f for f in packet.frames if f.available_at <= at]
    frame = frames[-1] if frames else None
    snapshot = frame.snapshot if frame else None
    if snapshot is not None and set(snapshot) - SNAPSHOT_FIELDS:
        # Reject subject/body/category/review fields rather than accidentally using them.
        return evaluate(packet.observation, None, None, at)
    source = _source(packet, frame, enrollment) if frame else None
    return evaluate(
        packet.observation,
        snapshot,
        source,
        at,
        providers=enrollment.agent_providers if enrollment else (),
    )


def _source(
    packet: DetectorPacket, frame: Frame, enrollment: Enrollment | None
) -> dict[str, Any] | None:
    capture = frame.source
    if capture is None:
        return None
    result: dict[str, Any] = {
        "observed_version": packet.observation.source_version,
        "expires_at": min(
            capture.expires_at.timestamp(),
            (packet.observation.observed_at + timedelta(days=7)).timestamp(),
        ),
        "status": "unavailable",
        "reason": "replay_source_unavailable",
        "evidence_refs": [],
    }
    if capture.state != "complete":
        if capture.state == "pending":
            result.update(status="pending", reason="audit_search_pending")
        return result
    if enrollment is None or enrollment.scope != packet.observation.scope:
        return result
    try:
        snapshot = frame.snapshot or {}
        if not enrolled_sender(snapshot, enrollment.mailbox_address):
            return result
        sent = datetime.fromisoformat(snapshot["sentDateTime"])
        query = capture.query
        if (
            not capture.pagination_complete
            or not capture.query_id
            or query.get("id") != capture.query_id
            or query.get("status") != "succeeded"
            or datetime.fromisoformat(query.get("filterStartDateTime", ""))
            != sent - timedelta(minutes=2)
            or datetime.fromisoformat(query.get("filterEndDateTime", ""))
            != sent + timedelta(minutes=2)
            or query.get("operationFilters") != ["Send"]
            or [v.lower() for v in query.get("recordTypeFilters", [])] != ["exchangeitem"]
            or [v.lower() for v in query.get("userPrincipalNameFilters", [])]
            != [enrollment.mailbox_address.lower()]
        ):
            result["reason"] = "replay_query_incomplete_or_out_of_scope"
            return result
        publisher = capture.publisher
        provider = provider_for_send(
            list(capture.records), snapshot["internetMessageId"], enrollment.agent_providers
        )
        client_id = str(provider.client_id) if provider else CLAUDE_APP
        current = (
            publisher.get("appId") == client_id
            and publisher.get("accountEnabled") is True
            and publisher.get("appOwnerOrganizationId")
            == (
                str(provider.publisher_owner_tenant)
                if provider
                else enrollment.publisher_owner_tenant
            )
            and publisher.get("verifiedPublisher", {}).get("verifiedPublisherId")
            == (provider.publisher_id if provider else enrollment.publisher_id)
        )
        status, reason, refs = qualify_exchange_send(
            list(capture.records),
            tenant=str(enrollment.scope.tenant_id),
            mailbox=enrollment.mailbox_address,
            mailbox_guid=enrollment.exchange_mailbox_guid,
            message_id=snapshot["internetMessageId"],
            sent_at=sent,
            publisher_current=current,
            client_id=client_id,
        )
        good = bool(capture.sent_folder_id) and corroborated_copy_context(
            packet.observation, snapshot, list(capture.copies), str(capture.sent_folder_id)
        )
        if status == "verified_enrolled_send" and not good:
            status, reason = "conflicting", "message_copy_collision_or_context_conflict"
        result.update(
            status=status,
            reason=reason,
            evidence_refs=[*refs, "publisher-sha256:" + sha(publisher)],
        )
        if provider:
            result.update(
                provider_fingerprint=provider.fingerprint,
                provider_client_id=client_id,
                evidence_refs=[*result["evidence_refs"], provider.evidence_ref],
            )
        if good and status == "verified_enrolled_send":
            result.update(receipt_context="corroborated_scope_messageid_time")
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return result
