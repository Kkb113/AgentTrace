"""Independent semantics and qualification counterexamples, not an accuracy dataset."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from agenttrace_outlook.audit_source import ROOT, AuditReader, publisher_snapshot
from agenttrace_outlook.config import ReaderIdentity, RuntimeConfig, SenderSource
from agenttrace_outlook.contracts import Decision, Observation, Scope
from agenttrace_outlook.eligibility import require_annotation_eligible
from agenttrace_outlook.errors import OutlookError, SourceError
from agenttrace_outlook.rule_store import RuleStore
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.sender_rules import (
    CLAUDE_APP,
    evaluate,
    inspect_snapshot,
    qualify_exchange_send,
    sha,
)
from agenttrace_outlook.source_collector import SenderCollector
from agenttrace_outlook.state import StateStore

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
SCOPE = Scope(tenant_id=UUID(int=1), mailbox_id=UUID(int=2))
MAILBOX = "owner@example.invalid"
QUERY = str(UUID(int=4))


def source() -> SenderSource:
    return SenderSource(
        subscription_id=UUID(int=5),
        mailbox_address=MAILBOX,
        exchange_mailbox_guid=UUID(int=6),
        audit_identity=ReaderIdentity(client_id=UUID(int=7), certificate_thumbprint="a" * 40),
        publisher_id="fictional",
        publisher_owner_tenant=UUID(int=8),
    )


def snapshot() -> dict[str, Any]:
    return {
        "isDraft": False,
        "internetMessageId": "<fictional@example.invalid>",
        "sentDateTime": NOW.isoformat(),
        "receivedDateTime": NOW.isoformat(),
        "internetMessageHeaders": [
            {"name": "from", "value": MAILBOX},
            {"name": "message-id", "value": "<fictional@example.invalid>"},
            {"name": "date", "value": "Thu, 29 Oct 2026 12:00:00 +0000"},
            {
                "name": "received",
                "value": "by mail.example.invalid with ESMTP; Thu, 29 Oct 2026 12:00:00 +0000",
            },
        ],
    }


def observation(raw: dict[str, Any] | None = None) -> Observation:
    raw = raw or snapshot()
    return Observation(
        scope=SCOPE,
        message_id="received-one",
        source_version="version-one",
        observed_at=NOW,
        received_at=NOW,
        inspection_complete=True,
        source_digest=sha(raw),
    )


def event() -> dict[str, Any]:
    return {
        "id": "event-one",
        "organizationId": str(SCOPE.tenant_id),
        "userPrincipalName": MAILBOX,
        "operation": "Send",
        "createdDateTime": NOW.isoformat(),
        "auditData": {
            "Id": "event-one",
            "CreationTime": NOW.isoformat(),
            "OrganizationId": str(SCOPE.tenant_id),
            "TokenTenantId": str(SCOPE.tenant_id),
            "MailboxOwnerUPN": MAILBOX,
            "MailboxGuid": str(UUID(int=6)),
            "Operation": "Send",
            "Workload": "Exchange",
            "ResultStatus": "Succeeded",
            "ClientAppId": CLAUDE_APP,
            "AppAccessContext": {"ClientAppId": CLAUDE_APP},
            "ClientRequestId": "request-one",
            "Item": {"Id": "audit-store-item", "InternetMessageId": "<fictional@example.invalid>"},
        },
    }


def qualify(rows: list[dict[str, Any]], publisher: bool = True) -> tuple[str, str, tuple[str, ...]]:
    return qualify_exchange_send(
        rows,
        tenant=str(SCOPE.tenant_id),
        mailbox=MAILBOX,
        mailbox_guid=str(UUID(int=6)),
        message_id="<fictional@example.invalid>",
        sent_at=NOW,
        publisher_current=publisher,
    )


def install(store: StateStore, raw: dict[str, Any]) -> int:
    obs = observation(raw)
    store.observe([obs])
    with store.transaction(lease=store.lease) as db:
        db.execute(
            "INSERT INTO snapshots VALUES (?,?,?)",
            (obs.message_id, json.dumps(raw), (NOW + timedelta(days=7)).timestamp()),
        )
    return store.pending(1)[0][0]


def test_clean_manual_policy_is_human_capable_not_human_identity() -> None:
    raw = snapshot()
    result = evaluate(observation(raw), raw, None, NOW)
    assert result.inspection == "complete" and result.human_candidate is True
    assert (
        result.category == "Human-capable"
        and result.human_support == "supported_client_compatibility"
    )


def test_browser_agent_and_human_are_both_human_capable_under_owner_policy() -> None:
    # Ground truth deliberately stays outside detector input. Same received
    # observables can result from human clicks or agent-controlled browser clicks.
    raw = snapshot()
    obs = observation(raw)
    outputs = [
        evaluate(obs, copy.deepcopy(raw), None, NOW) for truth in ("manual_human", "browser_agent")
    ]
    assert outputs[0] == outputs[1]
    assert all(v.human_candidate and v.category == "Human-capable" for v in outputs)


@pytest.mark.parametrize(
    "name,value,reason",
    [
        ("x-ai-generated", "mcp-office365", "untrusted_agent_declaration"),
        ("x-ai-generated", "invented-agent", "untrusted_agent_declaration"),
        ("received", "by gmailapi.google.com with HTTPREST", "generic_api_submission"),
        ("auto-submitted", "auto-replied", "conventional_automation_indicator"),
        ("list-id", "example mailing list", "conventional_automation_indicator"),
        ("x-mailer", "python script", "automation_client_indicator"),
        ("user-agent", "curl/8.0", "automation_client_indicator"),
    ],
)
def test_hints_and_ordinary_automation_never_become_agent_proof(
    name: str, value: str, reason: str
) -> None:
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": name, "value": value})
    result = evaluate(observation(raw), raw, None, NOW)
    assert (
        result.category == "Unknown"
        and not result.human_candidate
        and reason in result.reason_codes
    )


@pytest.mark.parametrize(
    "change",
    ["missing", "duplicate", "mismatch", "oversize", "draft", "naive_time", "newline_injection"],
)
def test_incomplete_or_conflicting_inspection_blocks_manual_candidate(change: str) -> None:
    raw = snapshot()
    if change == "missing":
        raw["internetMessageHeaders"].pop(0)
    elif change == "duplicate":
        raw["internetMessageHeaders"].append(raw["internetMessageHeaders"][0])
    elif change == "mismatch":
        raw["internetMessageId"] = "<other@example.invalid>"
    elif change == "oversize":
        raw["internetMessageHeaders"][0]["value"] = "a" * 140000
    elif change == "draft":
        raw["isDraft"] = True
    elif change == "naive_time":
        raw["sentDateTime"] = "2026-10-29T12:00:00"
    else:
        raw["internetMessageHeaders"][0]["value"] = (
            "owner@example.invalid\r\nx-ai-generated: mcp-office365"
        )
    result = evaluate(observation(raw), raw, None, NOW)
    assert (
        result.category == "Unknown"
        and not result.human_candidate
        and result.inspection != "complete"
    )


def test_snapshot_hash_mismatch_is_incomplete() -> None:
    raw = snapshot()
    obs = observation(raw)
    raw["isDraft"] = True
    assert inspect_snapshot(obs, raw)[0] == "incomplete"


def test_authenticated_action_and_exact_replay_semantics() -> None:
    row = event()
    assert qualify([row])[0] == "verified_enrolled_send"
    assert qualify([row, copy.deepcopy(row)])[0] == "verified_enrolled_send"
    assert qualify([row], publisher=False)[0] == "not_established"


@pytest.mark.parametrize(
    "field,value",
    [
        ("Operation", "Read"),
        ("Operation", "Create"),
        ("ResultStatus", "Failed"),
        ("ClientAppId", "ordinary-api-client"),
        ("TokenTenantId", str(UUID(int=9))),
        ("MailboxGuid", str(UUID(int=9))),
        ("MailboxOwnerUPN", "other@example.invalid"),
        ("ClientRequestId", ""),
        ("ClientRequestId", True),
        ("Workload", "SharePoint"),
        ("CreationTime", (NOW + timedelta(minutes=5)).isoformat()),
        ("AppAccessContext", {"ClientAppId": "other-client"}),
        ("Item", None),
    ],
)
def test_drafts_failures_generic_api_recipient_reads_and_wrong_scope_reject(
    field: str, value: Any
) -> None:
    row = event()
    row["auditData"][field] = value
    assert qualify([row])[0] != "verified_enrolled_send"


def test_conflicting_events_and_reused_ids_reject() -> None:
    row = event()
    other = copy.deepcopy(row)
    other["auditData"]["ClientAppId"] = "other"
    assert qualify([row, other])[0] == "conflicting"
    other["id"] = "event-two"
    other["auditData"]["Id"] = "event-two"
    assert qualify([row, other])[0] == "conflicting"


def test_copied_internet_ids_cannot_promote_source_action_to_receipt() -> None:
    raw = snapshot()
    obs = observation(raw)
    status, reason, refs = qualify([event()])
    source_packet = {
        "observed_version": obs.source_version,
        "status": status,
        "reason": reason,
        "evidence_refs": refs,
        "expires_at": (NOW + timedelta(minutes=5)).timestamp(),
    }
    result = evaluate(obs, raw, source_packet, NOW)
    assert (
        result.agent_execution == "verified_enrolled_send" and result.receipt_link == "unqualified"
    )
    assert result.category == "Unknown" and not result.human_candidate
    # Copying that ID into another received item cannot create an AI verdict.
    second = obs.model_copy(update={"message_id": "copied-received-id"})
    assert evaluate(second, raw, source_packet, NOW).category == "Unknown"


@pytest.mark.parametrize(
    "status", ["pending", "unavailable", "conflicting", "verified_enrolled_send"]
)
def test_staleness_revocation_outages_and_conflicts_never_produce_affirmative(status: str) -> None:
    raw = snapshot()
    obs = observation(raw)
    packet = {
        "observed_version": obs.source_version,
        "status": status,
        "reason": "publisher_unavailable_or_revoked",
        "expires_at": NOW.timestamp(),
    }
    result = evaluate(obs, raw, packet, NOW)
    assert result.category == "Unknown" and not result.human_candidate


def test_writer_rejects_asserted_positive_qualifications() -> None:
    for category in ("Human", "AI Agent"):
        candidate = Decision(
            scope=SCOPE,
            message_id="one",
            source_version="v1",
            category=category,
            rule_version="sender-positive/v1",
            basis="production",
            qualification="qualified",
            reason_codes=("asserted",),
            evidence_refs=("forged-proof",),
            decided_at=NOW,
            expires_at=NOW + timedelta(days=1),
        )
        with pytest.raises(OutlookError, match="rule_not_enrolled_or_qualified"):
            require_annotation_eligible(candidate, SCOPE, NOW)


def test_durable_reassessment_downgrade_and_replay_idempotence(tmp_path: Path) -> None:
    current = NOW
    cfg = RuntimeConfig(scope=SCOPE, state_directory=str(tmp_path))
    with StateStore(cfg, clock=lambda: current) as store:
        raw = snapshot()
        item = install(store, raw)
        assert run_once(store) == 1
        rules = RuleStore(store)
        job = dict(store.db.execute("SELECT * FROM rule_jobs").fetchone())
        status, reason, refs = qualify([event()])
        rules.capture(job, observation(raw), status=status, reason=reason, refs=refs)
        assert run_once(store) == 1
        assert store.summary()["decisions"] == 2
        rules.capture(job, observation(raw), status=status, reason=reason, refs=refs)
        assert run_once(store) == 1 and store.summary()["decisions"] == 2
        current += timedelta(seconds=301)
        store.db.execute("UPDATE lease SET expires=?", (current.timestamp() + 120,))
        run_once(store)
        assert store.summary()["decisions"] == 3
        result = json.loads(
            store.db.execute(
                "SELECT payload FROM rule_assessments WHERE observation_id=?", (item,)
            ).fetchone()[0]
        )
        assert result["agent_execution"] == "unavailable" and result["category"] == "Unknown"


class Audit:
    def __init__(self) -> None:
        self.calls = []
        self.sent = NOW
        self.row = event()

    def request(self, method: str, url: str, **kwargs: Any) -> dict:
        self.calls.append((method, url, kwargs))
        if method == "POST":
            self.body = kwargs["body"]
            return {"id": QUERY}
        if "/records" in url:
            return {"value": [self.row]}
        return {"id": QUERY, "status": "succeeded", **self.body}


def test_analytical_search_fixed_scope_and_unsafe_page_rejection(tmp_path: Path) -> None:
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )
    transport = Audit()
    reader = AuditReader(cfg, transport)
    assert reader.create(NOW) == QUERY
    assert transport.body["operationFilters"] == ["Send"] and transport.body[
        "userPrincipalNameFilters"
    ] == [MAILBOX]
    assert transport.calls[0][0:2] == ("POST", ROOT)
    with pytest.raises(SourceError):
        reader.records(QUERY, "https://evil.invalid/records")
    assert len(transport.calls) == 1


def test_resumable_source_collection_never_promotes_received_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = NOW
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )
    transport = Audit()
    monkeypatch.setattr(
        "agenttrace_outlook.source_collector.publisher_snapshot",
        lambda config: {"appId": CLAUDE_APP, "pin": "fictional"},
    )
    with StateStore(cfg, clock=lambda: current) as store:
        install(store, snapshot())
        collector = SenderCollector(store, AuditReader(cfg, transport))
        assert collector.step()
        run_once(store)
        assert not collector.step()
        current += timedelta(seconds=31)
        assert collector.step()
        assert collector.step()
        run_once(store)
        assessment = json.loads(
            store.db.execute("SELECT payload FROM rule_assessments").fetchone()[0]
        )
        assert assessment["agent_execution"] == "verified_enrolled_send"
        assert assessment["category"] == "Unknown" and assessment["receipt_link"] == "unqualified"
        assert all("/messages" not in call[1] for call in transport.calls)


class Copies:
    def __init__(self, extra: bool = False):
        self.extra = extra

    def well_known(self, name: str) -> dict:
        return {"id": "sent-folder"}

    def message_copies(self, message_id: str, cursor: str | None = None) -> dict:
        rows = [
            {
                "id": "sent-one",
                "parentFolderId": "sent-folder",
                "isDraft": False,
                "internetMessageId": message_id,
                "sentDateTime": NOW.isoformat(),
            },
            {
                "id": "received-one",
                "parentFolderId": "inbox",
                "isDraft": False,
                "internetMessageId": message_id,
                "sentDateTime": NOW.isoformat(),
            },
        ]
        if self.extra:
            rows.append({**rows[1], "id": "copied-received-id"})
        return {"value": rows}


@pytest.mark.parametrize("collision", [False, True])
def test_approved_corroborated_rule_and_observable_copy_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, collision: bool
) -> None:
    current = NOW
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )
    monkeypatch.setattr(
        "agenttrace_outlook.source_collector.publisher_snapshot",
        lambda config: {"appId": CLAUDE_APP, "pin": "fictional"},
    )
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    with StateStore(cfg, clock=lambda: current) as store:
        install(store, raw)
        collector = SenderCollector(store, AuditReader(cfg, Audit()), mail=Copies(extra=collision))
        collector.step()
        run_once(store)
        current += timedelta(seconds=31)
        for _ in range(3):
            collector.step()
        run_once(store)
        a = json.loads(store.db.execute("SELECT payload FROM rule_assessments").fetchone()[0])
        assert a["category"] == ("Unknown" if collision else "AI Agent")
        if not collision:
            assert a["receipt_link"] == "corroborated_indicators"
            assert "corroborated_poc_indicators_not_forensic_identity" in a["reason_codes"]
        else:
            assert a["agent_execution"] == "conflicting"


def test_corroboration_cannot_distinguish_an_unobservable_full_replacement() -> None:
    # Explicitly accepted POC limitation: if a forged replacement preserves all
    # observed correlation fields and leaves no observable collision, these
    # indicators are not independent forensic identity proof. Never report this
    # authored counterexample as an accurately rejected negative.
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    obs = observation(raw)
    packet = {
        "observed_version": obs.source_version,
        "status": "verified_enrolled_send",
        "evidence_refs": ("audit-sha256:" + "a" * 64, "publisher-sha256:" + "b" * 64),
        "expires_at": (NOW + timedelta(minutes=5)).timestamp(),
        "receipt_context": "corroborated_scope_messageid_time",
    }
    assert evaluate(obs, raw, packet, NOW).category == "AI Agent"


def test_snapshot_bound_positive_cannot_be_forged_with_just_a_rule_name(tmp_path: Path) -> None:
    cfg = RuntimeConfig(scope=SCOPE, state_directory=str(tmp_path))
    with StateStore(cfg, clock=lambda: NOW) as store:
        raw = snapshot()
        item = install(store, raw)
        false = Decision(
            scope=SCOPE,
            message_id="received-one",
            source_version="version-one",
            category="AI Agent",
            rule_version="sender-rules/claude-corroborated/v1",
            basis="production",
            qualification="qualified",
            reason_codes=("asserted",),
            evidence_refs=(
                "audit-sha256:" + "a" * 64,
                "publisher-sha256:" + "b" * 64,
                "snapshot-sha256:" + sha(raw),
            ),
            decided_at=NOW,
            expires_at=NOW + timedelta(days=1),
        )
        with pytest.raises(OutlookError, match="sender_decision_not_supported"):
            store.record_decision(item, false)
        assert store.summary()["decisions"] == 0


@pytest.mark.parametrize("approval", ["human_approved", "autonomous"])
def test_agent_action_does_not_depend_on_approval_or_text_origin(approval: str) -> None:
    row = event()
    row["auditData"]["ApprovalMode"] = approval
    assert qualify([row])[0] == "verified_enrolled_send"
    raw = snapshot()
    before = evaluate(observation(raw), raw, None, NOW)
    assert before.category == "Human-capable"  # Pasted AI drafting is not a send signal.


def test_folded_headers_are_supported_but_unfolded_injection_is_not() -> None:
    raw = snapshot()
    raw["internetMessageHeaders"][-1]["value"] = "by mail.example.invalid\r\n with ESMTP"
    assert inspect_snapshot(observation(raw), raw)[0] == "complete"


@pytest.mark.parametrize("value", [None, True, {}, []])
def test_malformed_audit_scope_fields_fail_closed(value: Any) -> None:
    row = event()
    row["auditData"]["MailboxOwnerUPN"] = value
    assert qualify([row])[0] == "conflicting"


def test_assessment_decision_and_preview_roll_back_together(tmp_path: Path) -> None:
    with StateStore(
        RuntimeConfig(scope=SCOPE, state_directory=str(tmp_path)), clock=lambda: NOW
    ) as store:
        install(store, snapshot())
        store.db.execute(
            "CREATE TEMP TRIGGER stop_preview BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'synthetic'); END"
        )
        with pytest.raises(OutlookError, match="state_transaction_failed"):
            run_once(store)
        assert store.db.execute("SELECT count(*) FROM rule_assessments").fetchone()[0] == 0
        assert store.summary()["decisions"] == 0


def test_enrolled_publisher_revocation_blocks_and_explicit_retry_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )

    def revoked(config: RuntimeConfig) -> dict:
        raise SourceError("publisher_pin_mismatch_or_revoked")

    monkeypatch.setattr("agenttrace_outlook.source_collector.publisher_snapshot", revoked)
    with StateStore(cfg, clock=lambda: NOW) as store:
        install(store, snapshot())
        collector = SenderCollector(store, AuditReader(cfg, Audit()))
        assert collector.step()
        run_once(store)
        assert collector.rules.summary()["source_blocked"] == 1
        assert (
            json.loads(store.db.execute("SELECT payload FROM rule_assessments").fetchone()[0])[
                "category"
            ]
            == "Unknown"
        )
        assert collector.rules.retry_failed() == 1
        assert collector.rules.summary()["source_blocked"] == 0


def test_late_window_closes_without_inventing_an_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = NOW
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )
    with StateStore(cfg, clock=lambda: current) as store:
        install(store, snapshot())
        collector = SenderCollector(store, AuditReader(cfg, Audit()))
        current += timedelta(hours=25)
        store.db.execute("UPDATE lease SET expires=?", (current.timestamp() + 120,))
        assert collector.step()
        run_once(store)
        assert store.db.execute("SELECT stage FROM rule_jobs").fetchone()[0] == "closed"
        a = json.loads(store.db.execute("SELECT payload FROM rule_assessments").fetchone()[0])
        assert a["category"] == "Unknown" and "late_observation_window_closed" in a["reason_codes"]


def test_source_enrollment_change_cannot_reuse_prior_receipts(tmp_path: Path) -> None:
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )
    with StateStore(cfg, clock=lambda: NOW) as store:
        RuleStore(store).prepare()
    changed = cfg.model_copy(
        update={"sender_source": source().model_copy(update={"publisher_id": "different"})}
    )
    with StateStore(changed, clock=lambda: NOW) as store:
        with pytest.raises(OutlookError, match="sender_enrollment_changed_requires_review"):
            RuleStore(store).prepare()
    rotated = cfg.model_copy(
        update={
            "sender_source": source().model_copy(
                update={
                    "refresh_seconds": 600,
                    "audit_identity": source().audit_identity.model_copy(
                        update={"certificate_thumbprint": "b" * 40}
                    ),
                }
            )
        }
    )
    with StateStore(rotated, clock=lambda: NOW) as store:
        RuleStore(store).prepare()


@pytest.mark.parametrize(
    "response", [[], {"value": None}, {"value": [None]}, {"value": [{"verifiedPublisher": None}]}]
)
def test_malformed_publisher_response_becomes_a_source_failure(
    response: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = RuntimeConfig(
        scope=SCOPE,
        state_directory=str(tmp_path),
        sender_source=source(),
        sync_enabled=True,
        reader_identity=source().audit_identity,
    )
    responses = iter([{"tenantId": str(SCOPE.tenant_id)}, response])
    monkeypatch.setattr(
        "agenttrace_outlook.audit_source.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(next(responses)).encode()
        ),
    )
    with pytest.raises(SourceError, match="publisher_registry_shape_invalid"):
        publisher_snapshot(cfg)
