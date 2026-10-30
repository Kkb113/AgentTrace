"""Provider enrollment, ordinary API counterexamples and the real durable decision path."""

import copy
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

from agenttrace_outlook.agent_providers import AgentProvider
from agenttrace_outlook.audit_source import AuditReader, publisher_snapshot
from agenttrace_outlook.config import RuntimeConfig
from agenttrace_outlook.eligibility import require_annotation_eligible
from agenttrace_outlook.errors import OutlookError, SourceError
from agenttrace_outlook.rule_store import RuleStore
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.sender_rules import PROVIDER_RULE, evaluate, qualify_exchange_send, sha
from agenttrace_outlook.source_collector import SenderCollector
from agenttrace_outlook.state import StateStore
from tests.unit.test_sender_rules import (
    MAILBOX,
    NOW,
    SCOPE,
    Audit,
    Copies,
    event,
    install,
    observation,
    snapshot,
    source,
)


def profile() -> AgentProvider:
    return AgentProvider(
        provider_key="fictional_agent",
        client_id=UUID(int=50),
        publisher_id="fictional_publisher",
        publisher_owner_tenant=UUID(int=51),
        declaration="authenticated_application",
    )


def config(path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        scope=SCOPE,
        state_directory=str(path),
        sync_enabled=True,
        reader_identity=source().audit_identity,
        sender_source=source().model_copy(update={"agent_providers": (profile(),)}),
    )


def provider_event() -> dict:
    row = event()
    row["auditData"]["ClientAppId"] = str(profile().client_id)
    row["auditData"]["AppAccessContext"]["ClientAppId"] = str(profile().client_id)
    return row


def evidence() -> dict:
    return {
        "observed_version": observation().source_version,
        "expires_at": (NOW + timedelta(minutes=5)).timestamp(),
        "status": "verified_enrolled_send",
        "receipt_context": "corroborated_scope_messageid_time",
        "provider_fingerprint": profile().fingerprint,
        "provider_client_id": str(profile().client_id),
        "evidence_refs": (
            "audit-sha256:" + "a" * 64,
            "publisher-sha256:" + "b" * 64,
            profile().evidence_ref,
        ),
    }


def test_authenticated_enrolled_application_needs_no_invented_header() -> None:
    raw = snapshot()
    verdict = evaluate(observation(raw), raw, evidence(), NOW, providers=(profile(),))
    assert verdict.category == "AI Agent" and verdict.rule_version == PROVIDER_RULE
    assert "enrolled_application_send_corroborated" in verdict.reason_codes
    assert evaluate(observation(raw), raw, evidence(), NOW).category == "Unknown"


@pytest.mark.parametrize("change", ["pin", "client", "ref", "expired", "copies", "declaration"])
def test_missing_or_changed_proof_cannot_be_promoted(change: str) -> None:
    raw, packet = snapshot(), evidence()
    if change == "pin":
        packet["provider_fingerprint"] = "0" * 64
    elif change == "client":
        packet["provider_client_id"] = str(UUID(int=52))
    elif change == "ref":
        packet["evidence_refs"] = packet["evidence_refs"][:-1]
    elif change == "expired":
        packet["expires_at"] = NOW.timestamp()
    elif change == "copies":
        packet["receipt_context"] = "unqualified"
    else:
        raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "another_agent"})
    assert (
        evaluate(observation(raw), raw, packet, NOW, providers=(profile(),)).category == "Unknown"
    )


def test_generic_api_trace_or_forged_brand_header_is_not_provider_identity() -> None:
    for name, value in (
        ("received", "by gmailapi.google.com with HTTPREST"),
        ("x-ai-generated", "chatgpt"),
    ):
        raw = snapshot()
        raw["internetMessageHeaders"].append({"name": name, "value": value})
        assert (
            evaluate(observation(raw), raw, None, NOW, providers=(profile(),)).category == "Unknown"
        )


@pytest.mark.parametrize("change", ["none", "nested", "failed", "wrong_mailbox", "wrong_time"])
def test_exact_application_send_identity_and_scope(change: str) -> None:
    row = provider_event()
    row["auditData"]["ClientInfoString"] = "Client=Outlook;Automation"
    if change == "nested":
        row["auditData"]["AppAccessContext"]["ClientAppId"] = "other_app"
    elif change == "failed":
        row["auditData"]["ResultStatus"] = "Failed"
    elif change == "wrong_mailbox":
        row["auditData"]["MailboxOwnerUPN"] = "other@example.invalid"
    elif change == "wrong_time":
        row["createdDateTime"] = (NOW + timedelta(seconds=3)).isoformat()
    result = qualify_exchange_send(
        [row],
        tenant=str(SCOPE.tenant_id),
        mailbox=MAILBOX,
        mailbox_guid=str(UUID(int=6)),
        message_id=snapshot()["internetMessageId"],
        sent_at=NOW,
        publisher_current=True,
        client_id=str(profile().client_id),
    )
    assert (result[0] == "verified_enrolled_send") == (change == "none")
    if change == "nested":
        assert result[0] != "normal_client_context"


def test_duplicate_or_reserved_profiles_are_rejected() -> None:
    data = source().model_dump(mode="json")
    data["agent_providers"] = [profile().model_dump(mode="json")] * 2
    with pytest.raises(ValidationError):
        type(source()).model_validate_json(json.dumps(data))


@pytest.mark.parametrize("collision", [False, True])
def test_resumable_collector_decision_and_write_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    collision: bool,
) -> None:
    current = NOW
    monkeypatch.setattr(
        "agenttrace_outlook.source_collector.publisher_snapshot",
        lambda cfg, provider: {"appId": str(provider.client_id)},
    )
    transport = Audit()
    transport.row = provider_event()
    cfg = config(tmp_path)
    with StateStore(cfg, clock=lambda: current) as store:
        install(store, snapshot())
        collector = SenderCollector(
            store, AuditReader(cfg, transport), mail=Copies(extra=collision)
        )
        collector.step()
        run_once(store)
        current += timedelta(seconds=31)
        for _ in range(3):
            collector.step()
        assert run_once(store) == 1
        from agenttrace_outlook.contracts import Decision

        decision = Decision.model_validate_json(
            store.db.execute("SELECT payload FROM decisions ORDER BY id DESC LIMIT 1").fetchone()[0]
        )
        assert decision.category == ("Unknown" if collision else "AI Agent")
        require_annotation_eligible(decision, SCOPE, current)
        from agenttrace_outlook.category_preview import category_preview
        from tests.unit.test_outlook_categories import provisioned

        _, registry, _ = provisioned(tmp_path / "ownership")
        obs = observation()
        args = (
            registry,
            tuple(c.category for c in registry.categories),
            decision,
            obs,
            snapshot(),
            RuleStore(store).source(1),
            {
                "id": obs.message_id,
                "subject": "AgentTrace synthetic test: preview",
                "isDraft": False,
                "categories": ["Personal"],
            },
            current,
        )
        assert category_preview(*args, providers=(profile(),))["category"] == decision.category
        if not collision:
            with pytest.raises(OutlookError):
                category_preview(*args)
        assert (
            store.db.execute("SELECT count(*) FROM work WHERE status='failed'").fetchone()[0] == 0
        )


def test_enrollment_addition_requires_review_and_legacy_hash_is_unchanged(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    legacy = cfg.model_copy(update={"sender_source": source()})
    with StateStore(legacy, clock=lambda: NOW) as store:
        RuleStore(store).prepare()
        expected = source().model_dump(
            mode="json", exclude={"audit_identity", "refresh_seconds", "agent_providers"}
        )
        expected["audit_client_id"] = str(source().audit_identity.client_id)
        assert store.db.execute(
            "SELECT value FROM metadata WHERE key='sender_enrollment'"
        ).fetchone()[0] == sha(expected)
    with StateStore(cfg, clock=lambda: NOW) as store:
        with pytest.raises(OutlookError, match="sender_enrollment_changed_requires_review"):
            RuleStore(store).prepare()


def test_profile_fields_and_capability_cannot_be_inferred_from_name() -> None:
    data = copy.deepcopy(profile().model_dump(mode="json"))
    data["send_evidence"] = "gmail_api_header"
    with pytest.raises(ValidationError):
        AgentProvider.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("change", ["none", "app", "publisher", "tenant", "disabled", "ambiguous"])
def test_registry_pins_are_exact_and_display_names_are_irrelevant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    row = {
        "appId": str(profile().client_id),
        "accountEnabled": True,
        "appOwnerOrganizationId": str(profile().publisher_owner_tenant),
        "verifiedPublisher": {"verifiedPublisherId": profile().publisher_id},
        "displayName": "This name is not a trust signal",
    }
    if change == "app":
        row["appId"] = str(UUID(int=61))
    elif change == "publisher":
        row["verifiedPublisher"]["verifiedPublisherId"] = "other"
    elif change == "tenant":
        row["appOwnerOrganizationId"] = str(UUID(int=61))
    elif change == "disabled":
        row["accountEnabled"] = False
    pages = iter(
        [
            {"tenantId": str(SCOPE.tenant_id)},
            {"value": [row, row] if change == "ambiguous" else [row]},
        ]
    )
    commands = []

    def request(command: list, **kwargs: object) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps(next(pages)).encode())

    monkeypatch.setattr("agenttrace_outlook.audit_source.subprocess.run", request)
    if change == "none":
        assert publisher_snapshot(config(tmp_path), profile()) == row
    else:
        with pytest.raises(SourceError):
            publisher_snapshot(config(tmp_path), profile())
    from urllib.parse import unquote_plus

    assert str(profile().client_id) in unquote_plus(" ".join(commands[-1]))


def test_provider_replay_uses_same_pinned_rule_and_rejects_revocation() -> None:
    from agenttrace_outlook.accuracy_contracts import DetectorPacket
    from agenttrace_outlook.accuracy_replay import replay
    from tests.sender_accuracy_support import NOW as REPLAY_NOW
    from tests.sender_accuracy_support import enrollment, packet

    enrolled = enrollment().model_copy(update={"agent_providers": (profile(),)})
    value = packet(REPLAY_NOW - timedelta(days=2), agent=True).model_dump(mode="json")
    for frame in value["frames"]:
        frame["snapshot"]["internetMessageHeaders"].pop()
        frame["source"]["publisher"] = {
            "appId": str(profile().client_id),
            "accountEnabled": True,
            "appOwnerOrganizationId": str(profile().publisher_owner_tenant),
            "verifiedPublisher": {"verifiedPublisherId": profile().publisher_id},
        }
        data = frame["source"]["records"][0]["auditData"]
        data["ClientAppId"] = data["AppAccessContext"]["ClientAppId"] = str(profile().client_id)
    value["observation"]["source_digest"] = sha(value["frames"][0]["snapshot"])
    at = __import__("datetime").datetime.fromisoformat(value["frames"][0]["available_at"])
    assert (
        replay(DetectorPacket.model_validate_json(json.dumps(value)), enrolled, at).category
        == "AI Agent"
    )
    value["frames"][0]["source"]["publisher"]["accountEnabled"] = False
    assert (
        replay(DetectorPacket.model_validate_json(json.dumps(value)), enrolled, at).category
        == "Unknown"
    )


def test_pending_audit_does_not_override_clean_human_compatibility_policy() -> None:
    packet = {**evidence(), "status": "pending", "reason": "audit_search_pending"}
    result = evaluate(observation(), snapshot(), packet, NOW, providers=(profile(),))
    assert result.category == "Human"
    assert result.agent_execution == "not_established"
    assert "compatible_path_does_not_establish_controller" in result.reason_codes
