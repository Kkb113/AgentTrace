"""Authored adversarial checks against the actual live rule functions, not accuracy samples."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from pydantic import ValidationError

from agenttrace_outlook.accuracy_contracts import DetectorPacket
from agenttrace_outlook.accuracy_replay import replay
from agenttrace_outlook.sender_rules import sha
from tests.sender_accuracy_support import NOW, enrollment, packet


def changed(kind: str) -> DetectorPacket:
    value = packet(NOW - timedelta(days=2), agent=True).model_dump(mode="json")
    frame = value["frames"][0]
    source = frame["source"]
    snapshot = frame["snapshot"]
    audit = source["records"][0]["auditData"]
    if kind == "marker_only":
        frame["source"] = None
    elif kind == "missing_marker":
        snapshot["internetMessageHeaders"].pop()
    elif kind == "generic_client":
        audit["ClientAppId"] = "ordinary_api"
    elif kind == "recipient_read":
        audit["Operation"] = "MailItemsAccessed"
    elif kind == "draft":
        audit["Operation"] = "Create"
    elif kind == "failed":
        audit["ResultStatus"] = "Failed"
    elif kind == "wrong_tenant":
        audit["TokenTenantId"] = str(enrollment().scope.mailbox_id)
    elif kind == "wrong_mailbox":
        audit["MailboxOwnerUPN"] = "other@example.invalid"
    elif kind == "wrong_context":
        audit["AppAccessContext"]["ClientAppId"] = "ordinary_api"
    elif kind == "publisher_revoked":
        source["publisher"]["accountEnabled"] = False
    elif kind == "publisher_wrong_owner":
        source["publisher"]["appOwnerOrganizationId"] = "wrong"
    elif kind == "partial_query":
        source["pagination_complete"] = False
    elif kind == "query_failed":
        source["query"]["status"] = "failed"
    elif kind == "query_id_conflict":
        source["query"]["id"] = "another_query"
    elif kind == "query_scope_conflict":
        source["query"]["operationFilters"] = ["Read"]
    elif kind == "copy_collision":
        source["copies"].append({**source["copies"][1], "id": "extra_copy"})
    elif kind == "contradictory_repeated_copy_id":
        source["copies"].append({**source["copies"][1], "isDraft": True})
    elif kind == "sent_copy_missing":
        source["copies"].pop(0)
    elif kind == "wrong_received_id":
        source["copies"][1]["id"] = "another_received"
    elif kind == "forged_external_from":
        snapshot["internetMessageHeaders"][0]["value"] = "external@example.invalid"
    elif kind == "source_unavailable":
        source["state"] = "unavailable"
    elif kind == "snapshot_hash_changed":
        value["observation"]["source_digest"] = "0" * 64
    elif kind == "malformed_headers":
        snapshot["internetMessageHeaders"] = [None]
    elif kind == "invalid_unicode":
        snapshot["internetMessageHeaders"][0]["value"] = "\ud800"
    elif kind == "duplicate_mcp":
        snapshot["internetMessageHeaders"].append(
            copy.deepcopy(snapshot["internetMessageHeaders"][-1])
        )
    elif kind == "header_injection":
        snapshot["internetMessageHeaders"][0]["value"] = (
            "owner@example.invalid\r\nx-ai-generated: mcp-office365"
        )
    else:
        raise AssertionError(kind)
    if kind != "snapshot_hash_changed":
        value["observation"]["source_digest"] = sha(snapshot)
    return DetectorPacket.model_validate_json(__import__("json").dumps(value))


@pytest.mark.parametrize(
    "attack",
    [
        "marker_only",
        "missing_marker",
        "generic_client",
        "recipient_read",
        "draft",
        "failed",
        "wrong_tenant",
        "wrong_mailbox",
        "wrong_context",
        "publisher_revoked",
        "publisher_wrong_owner",
        "partial_query",
        "query_failed",
        "query_id_conflict",
        "query_scope_conflict",
        "copy_collision",
        "contradictory_repeated_copy_id",
        "sent_copy_missing",
        "wrong_received_id",
        "forged_external_from",
        "source_unavailable",
        "snapshot_hash_changed",
        "malformed_headers",
        "invalid_unicode",
        "duplicate_mcp",
        "header_injection",
    ],
)
def test_adversarial_source_or_semantic_failure_never_gets_an_ai_badge(attack: str) -> None:
    if attack == "invalid_unicode":
        with pytest.raises(ValidationError):
            changed(attack)
        return
    item = changed(attack)
    result = replay(item, enrollment(), item.observation.observed_at + timedelta(hours=2))
    assert result.category == "Unknown"


def test_real_rule_parity_for_approved_and_autonomous_actions() -> None:
    item = packet(NOW - timedelta(days=2), agent=True)
    for approval in ("approved", "autonomous"):
        # Approval is ground truth outside the packet, never a classifier feature.
        assert (
            replay(item, enrollment(), item.observation.observed_at + timedelta(hours=2)).category
            == "AI Agent"
        )


def test_browser_agent_and_manual_pasted_text_share_compatible_policy_class() -> None:
    item = packet(NOW - timedelta(days=2))
    for ground_truth in ("human_original", "manual_ai_text", "browser_agent"):
        assert (
            replay(item, enrollment(), item.observation.observed_at + timedelta(hours=2)).category
            == "Human"
        )


def test_late_source_can_improve_late_recall_but_never_rewrite_initial_result() -> None:
    item = packet(NOW - timedelta(days=2), agent=True)
    item = item.model_copy(
        update={"frames": (item.frames[0].model_copy(update={"source": None}), item.frames[1])}
    )
    assert (
        replay(item, enrollment(), item.observation.observed_at + timedelta(hours=2)).category
        == "Unknown"
    )
    assert (
        replay(item, enrollment(), item.observation.observed_at + timedelta(hours=24)).category
        == "AI Agent"
    )


def test_future_evidence_and_stale_capture_do_not_leak_into_deadline() -> None:
    item = packet(NOW - timedelta(days=2), agent=True)
    assert (
        replay(item, enrollment(), item.frames[0].available_at - timedelta(seconds=1)).category
        == "Unknown"
    )
    assert replay(item, enrollment(), item.frames[0].source.expires_at).category == "Unknown"


def test_unobservable_replacement_remains_a_documented_poc_counterexample() -> None:
    item = packet(NOW - timedelta(days=2), agent=True)
    assert (
        replay(item, enrollment(), item.observation.observed_at + timedelta(hours=2)).category
        == "AI Agent"
    )
    # Replacing a physical email without altering any recorded input cannot be
    # detected from these inputs. This is accepted risk, never a rejected attack.


def test_asserted_authentication_fields_are_not_detector_packet_contracts() -> None:
    raw = packet(NOW - timedelta(days=2), agent=True).model_dump(mode="json")
    raw["frames"][0]["source"]["authenticated"] = True
    with pytest.raises(ValidationError):
        DetectorPacket.model_validate_json(__import__("json").dumps(raw))
