"""Integrated operator-mode label application, opt-in boundaries and recovery."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from agenttrace_outlook.category_application import ApplicationSettings, CategoryApplication
from agenttrace_outlook.category_ownership import OwnershipStore
from agenttrace_outlook.category_writer import CategoryWriter
from agenttrace_outlook.cli import main
from agenttrace_outlook.contracts import Decision, Observation
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.reader import MailReader
from agenttrace_outlook.rule_store import RuleStore
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.sender_rules import evaluate
from agenttrace_outlook.state import StateStore
from tests.unit.test_category_writer import setup
from tests.unit.test_outlook_sync import Graph
from tests.unit.test_sender_rules import snapshot


def files(tmp_path, store, writer):
    runtime = tmp_path / "runtime.json"
    settings = tmp_path / "settings.json"
    receipt = tmp_path / "qualification.json"
    runtime.write_text(store.config.model_dump_json())
    settings.write_text(writer.catalog.settings.model_dump_json())
    receipt.write_text(writer.qualification.model_dump_json())
    return runtime, settings, receipt


def arguments(paths):
    runtime, settings, receipt = paths
    return [
        "--config",
        str(runtime),
        "--apply-categories",
        "--category-settings",
        str(settings),
        "--category-qualification",
        str(receipt),
    ]


@pytest.mark.parametrize("mutation", ["scope", "reader", "not_live", "expired", "wrong_writer"])
def test_application_configuration_rejected_before_network_or_state(
    tmp_path, monkeypatch, mutation
):
    store, writer, server, clock, _, _ = setup(tmp_path)
    paths = files(tmp_path, store, writer)
    server.calls.clear()
    runtime, settings, receipt = paths
    cfg = store.config
    if mutation == "scope":
        cfg = cfg.model_copy(
            update={"scope": cfg.scope.model_copy(update={"mailbox_id": UUID(int=99)})}
        )
    elif mutation == "reader":
        cfg = cfg.model_copy(update={"reader_identity": writer.catalog.settings.writer_identity})
    elif mutation == "not_live":
        cfg = cfg.model_copy(update={"sync_enabled": False})
    elif mutation == "expired":
        clock.now += timedelta(days=8)
    elif mutation == "wrong_writer":
        value = writer.qualification.model_copy(update={"writer_client_id": UUID(int=99)})
        receipt.write_text(value.model_dump_json())
    store.close()
    monkeypatch.setattr(
        "agenttrace_outlook.category_application.datetime",
        type("Time", (), {"now": staticmethod(lambda zone: clock())}),
    )
    with pytest.raises(OutlookError):
        ApplicationSettings.read(cfg, settings, receipt)
    assert not server.calls


@pytest.mark.parametrize("extra", [[], ["--fixture", "missing.json"], ["--inspect-rules"]])
def test_apply_requires_complete_explicit_live_configuration(tmp_path, extra, capsys):
    store, writer, server, _, _, _ = setup(tmp_path)
    paths = files(tmp_path, store, writer)
    server.calls.clear()
    store.close()
    args = ["--config", str(paths[0]), "--apply-categories"]
    if extra:
        args = arguments(paths) + extra
    assert main(args) == 1
    assert "explicit_live_category_configuration_required" in capsys.readouterr().out
    assert not server.calls


def test_settings_without_apply_never_enable_writes(tmp_path, capsys):
    store, writer, server, _, _, _ = setup(tmp_path)
    paths = files(tmp_path, store, writer)
    server.calls.clear()
    store.close()
    assert main(["--config", str(paths[0]), "--category-settings", str(paths[1])]) == 1
    assert "category_settings_require_apply_flag" in capsys.readouterr().out
    assert server.patch_count == 0


def test_cycles_write_once_preserve_user_state_and_drain(tmp_path):
    store, writer, server, _, _, _ = setup(tmp_path)
    try:
        app = CategoryApplication(writer)
        assert app.run_cycle()[0]["status"] == "applied"
        assert app.summary()["category_health"] == "current"
        assert app.run_cycle() == []
        assert server.patch_count == 1
        assert server.item["categories"] == ["Personal", "Human"]
        assert server.item["isRead"] is False
        assert all(set(c[2]["body"]) == {"categories"} for c in server.calls if c[0] == "PATCH")
    finally:
        store.close()


def test_uncertain_send_recovers_on_monitor_restart_without_duplicate_patch(tmp_path):
    store, writer, server, clock, _, _ = setup(tmp_path)
    cfg, catalog, registry, qualification = (
        store.config,
        writer.catalog,
        writer.registry,
        writer.qualification,
    )
    try:
        server.mode = "timeout_after"
        app = CategoryApplication(writer)
        assert app.run_cycle()[0]["status"] == "uncertain"
        assert app.summary()["category_health"] == "pending"
        assert app.run_cycle() == []  # Retry-After is respected.
    finally:
        store.close()
    clock.advance()
    with StateStore(cfg, clock=clock) as restarted:
        app = CategoryApplication(CategoryWriter(restarted, catalog, registry, qualification))
        assert app.run_cycle()[0]["status"] == "reconciled"
        assert app.summary()["category_reconciled"] == 1
        assert server.patch_count == 1


def test_denied_write_is_blocked_and_not_automatically_retried(tmp_path):
    store, writer, server, _, _, _ = setup(tmp_path)
    try:
        server.mode = "forbidden"
        app = CategoryApplication(writer)
        assert app.run_cycle()[0]["status"] == "blocked"
        assert app.summary()["category_health"] == "degraded"
        assert app.run_cycle() == []
        assert server.patch_count == 1
        assert server.item["categories"] == ["Personal"]
    finally:
        store.close()


def test_old_invalid_decision_does_not_starve_newer_work(tmp_path):
    store, writer, server, clock, identity, _ = setup(tmp_path)
    try:
        with store.transaction(lease=store.lease) as db:
            db.execute("DELETE FROM category_intents")
            decision = Decision.model_validate_json(
                writer.store.db.execute("SELECT payload FROM decisions").fetchone()[0]
            )
            expired = decision.model_copy(update={"expires_at": clock() + timedelta(seconds=1)})
            db.execute("UPDATE decisions SET payload=?", (expired.model_dump_json(),))
        clock.now += timedelta(seconds=2)
        app = CategoryApplication(writer)
        assert app.run_cycle() == []
        assert app.summary()["category_blocked"] == 1
        assert app.run_cycle() == []
        assert server.patch_count == 0
    finally:
        store.close()


def test_out_of_scope_history_is_not_planned_or_counted_as_current_failure(tmp_path):
    store, writer, server, _, identity, _ = setup(tmp_path)
    try:
        with store.transaction(lease=store.lease) as db:
            db.execute("UPDATE category_intents SET status='blocked',error_code='old_failure'")
            db.execute("UPDATE sync_items SET status='excluded'")
        app = CategoryApplication(writer)
        assert app.run_cycle() == []
        assert app.summary()["category_health"] == "current"
        assert writer.summary(identity)["status"] == "blocked"  # History is retained.
        with store.transaction(lease=store.lease) as db:
            db.execute("DELETE FROM category_intents")
        assert app.run_cycle() == []
        assert server.patch_count == 0
    finally:
        store.close()


def test_unresolved_out_of_scope_write_remains_visible(tmp_path):
    store, writer, server, clock, _, _ = setup(tmp_path)
    try:
        server.mode = "timeout_after"
        app = CategoryApplication(writer)
        assert app.run_cycle()[0]["status"] == "uncertain"
        with store.transaction(lease=store.lease) as db:
            db.execute("UPDATE sync_items SET status='excluded'")
        assert app.summary()["category_pending"] == 1
        clock.advance()
        assert app.run_cycle()[0]["status"] == "uncertain"
        assert server.patch_count == 1
    finally:
        store.close()


@pytest.mark.parametrize(
    "name,value",
    [
        ("received", "by gmailapi.google.com with HTTPREST"),
        ("auto-submitted", "auto-replied"),
        ("x-ai-generated", "mcp-office365"),
    ],
)
def test_unqualified_headers_and_conventional_automation_receive_unknown(tmp_path, name, value):
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": name, "value": value})
    store, writer, server, _, _, _ = setup(tmp_path, raw=raw)
    try:
        result = CategoryApplication(writer).run_cycle()[0]
        assert result["classification"] == "Unknown"
        assert result["status"] == "applied"
        assert server.item["categories"] == ["Personal", "Unknown"]
    finally:
        store.close()


def test_late_verified_source_replaces_unknown_and_expiry_downgrades_without_loop(tmp_path):
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    store, writer, server, clock, _, _ = setup(tmp_path, raw=raw)
    try:
        app = CategoryApplication(writer)
        assert app.run_cycle()[0]["classification"] == "Unknown"
        rules = RuleStore(store)
        job = dict(store.db.execute("SELECT * FROM rule_jobs").fetchone())
        observation = writer.row(1)["observation"]
        rules.capture(
            job,
            Observation.model_validate_json(observation),
            status="verified_enrolled_send",
            reason="authenticated_enrolled_send",
            refs=("audit-sha256:" + "a" * 64, "publisher-sha256:" + "b" * 64),
            receipt_context="corroborated_scope_messageid_time",
        )
        assert run_once(store) == 1
        assert app.run_cycle()[0]["classification"] == "AI Agent"
        assert server.item["categories"] == ["Personal", "AI Agent"]
        assert app.run_cycle() == []
        for _ in range(6):
            clock.now += timedelta(seconds=60)
            store.heartbeat()
        assert run_once(store) == 1
        assert app.run_cycle()[0]["classification"] == "Unknown"
        assert server.item["categories"] == ["Personal", "Unknown"]
        assert server.patch_count == 3
        assert app.run_cycle() == []
    finally:
        store.close()


@pytest.mark.parametrize("source_status", [None, "pending", "unavailable"])
def test_optional_mcp_marker_policy_is_explicit_and_discloses_spoofing(source_status):
    from tests.unit.test_sender_rules import NOW, observation

    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    obs = observation(raw)
    source = (
        None
        if source_status is None
        else {
            "observed_version": obs.source_version,
            "status": source_status,
            "expires_at": (NOW + timedelta(minutes=5)).timestamp(),
        }
    )
    assert evaluate(obs, raw, source, NOW).category == "Unknown"
    result = evaluate(obs, raw, source, NOW, allow_known_mcp_marker=True)
    assert result.category == "AI Agent"
    assert result.receipt_link == "header_indicator"
    assert result.agent_execution != "verified_enrolled_send"
    assert "known_mcp_marker_poc_indicator_spoofable" in result.reason_codes


@pytest.mark.parametrize(
    "mutation", ["duplicate", "other_marker", "api_only", "auto_reply", "conflict", "incomplete"]
)
def test_poc_marker_mode_still_rejects_unsupported_or_conflicting_evidence(mutation):
    from tests.unit.test_sender_rules import NOW, observation

    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    source = None
    if mutation == "duplicate":
        raw["internetMessageHeaders"].append(raw["internetMessageHeaders"][-1])
    elif mutation == "other_marker":
        raw["internetMessageHeaders"][-1]["value"] = "invented"
    elif mutation == "api_only":
        raw["internetMessageHeaders"][-1] = {
            "name": "received",
            "value": "by gmailapi.google.com with HTTPREST",
        }
    elif mutation == "auto_reply":
        raw["internetMessageHeaders"].append({"name": "auto-submitted", "value": "auto-replied"})
    elif mutation == "incomplete":
        raw["internetMessageHeaders"].pop(0)
    obs = observation(raw)
    if mutation == "conflict":
        source = {
            "observed_version": obs.source_version,
            "status": "conflicting",
            "expires_at": (NOW + timedelta(minutes=5)).timestamp(),
        }
    assert evaluate(obs, raw, source, NOW, allow_known_mcp_marker=True).category == "Unknown"


def test_marker_policy_flips_reassess_and_writer_cannot_reuse_it_in_strict_mode(tmp_path):
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    store, writer, server, _, _, _ = setup(tmp_path, raw=raw)
    try:
        app = CategoryApplication(writer)
        assert app.run_cycle()[0]["classification"] == "Unknown"
        store.config = store.config.model_copy(update={"known_mcp_marker_poc_enabled": True})
        assert run_once(store) == 1
        ids = writer.plan()
        assert len(ids) == 1
        store.config = store.config.model_copy(update={"known_mcp_marker_poc_enabled": False})
        assert writer.step(ids[0])["status"] == "blocked"
        assert server.item["categories"] == ["Personal", "Unknown"]
        store.config = store.config.model_copy(update={"known_mcp_marker_poc_enabled": True})
        writer.request_retry(ids[0])
        assert app.run_cycle()[0]["classification"] == "AI Agent"
        assert server.item["categories"] == ["Personal", "AI Agent"]
        assert app.run_cycle() == []
    finally:
        store.close()


@pytest.mark.parametrize(
    "status,reason",
    [
        ("pending", "audit_search_pending"),
        ("normal_client_context", "browser_or_normal_client_context"),
        ("not_established", "completed_send_evidence_missing"),
    ],
)
def test_clean_manual_classification_is_stable_across_audit_refresh_expiry(status, reason):
    from tests.unit.test_sender_rules import NOW, observation

    raw = snapshot()
    obs = observation(raw)
    packet = {
        "status": status,
        "reason": reason,
        "observed_version": obs.source_version,
        "expires_at": NOW.timestamp(),
    }
    result = evaluate(obs, raw, packet, NOW + timedelta(minutes=1), allow_known_mcp_marker=True)
    assert result.category == "Human"
    assert result.agent_execution != "verified_enrolled_send"


@pytest.mark.parametrize(
    "mutation", ["none", "ordinary_script", "duplicate", "different_http", "conflict", "incomplete"]
)
def test_gmail_api_poc_is_opt_in_and_does_not_claim_agent_specific_evidence(mutation):
    from tests.unit.test_sender_rules import NOW, observation

    raw = snapshot()
    raw["internetMessageHeaders"].append(
        {"name": "received", "value": "by gmailapi.google.com with HTTPREST"}
    )
    if mutation == "duplicate":
        raw["internetMessageHeaders"].append(raw["internetMessageHeaders"][-1])
    elif mutation == "different_http":
        raw["internetMessageHeaders"][-1]["value"] = "by mail.example.invalid with HTTPREST"
    elif mutation == "incomplete":
        raw["internetMessageHeaders"].pop(0)
    obs = observation(raw)
    source = (
        None
        if mutation != "conflict"
        else {
            "observed_version": obs.source_version,
            "status": "conflicting",
            "expires_at": (NOW + timedelta(minutes=5)).timestamp(),
        }
    )
    result = evaluate(obs, raw, source, NOW, allow_gmail_api_poc=True)
    if mutation in {"none", "ordinary_script", "duplicate"}:
        assert evaluate(obs, raw, source, NOW).category == "Unknown"
        assert result.category == "AI Agent"
        assert result.agent_execution != "verified_enrolled_send"
        assert "gmail_api_poc_indicator_not_agent_specific" in result.reason_codes
    elif mutation == "different_http":
        assert result.category == "Human"
    else:
        assert result.category == "Unknown"


@pytest.mark.parametrize(
    "subject",
    [
        "",
        "A custom message",
        "Invoice 3492",
        "\u65e5\u672c\u8a9e",
        "AgentTrace synthetic test: legacy",
    ],
)
@pytest.mark.parametrize("agent", [False, True])
def test_every_incoming_subject_is_collected_and_labeled(tmp_path, subject, agent):
    from tests.unit.test_outlook_sync import requeue, settle

    raw = snapshot()
    if agent:
        raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    store, writer, server, _, _, sync = setup(tmp_path, raw=raw)
    try:
        server.item["subject"] = subject
        sync.reader._transport.messages[server.item["id"]] = server.item
        requeue(sync, server.item["id"])
        settle(sync)
        if agent:
            store.config = store.config.model_copy(update={"known_mcp_marker_poc_enabled": True})
            run_once(store)
        assert sync.state.summary()["sync_eligible_items"] == 1
        result = CategoryApplication(writer).run_cycle()[-1]
        assert result["status"] in {"applied", "unchanged"}
        expected = "AI Agent" if agent else "Human"
        assert result["classification"] == expected
        assert server.item["categories"] == ["Personal", expected]
    finally:
        store.close()


@pytest.mark.parametrize(
    "apply,deny,fast",
    [(False, False, False), (True, False, False), (True, True, False), (True, False, True)],
)
def test_actual_cli_collection_decision_application_and_restart(
    tmp_path, monkeypatch, capsys, apply, deny, fast
):
    store, writer, server, clock, _, _ = setup(tmp_path)
    cfg = store.config.model_copy(update={"state_directory": str(tmp_path / "fresh-state")})
    if fast:
        from tests.unit.test_sender_rules import source

        cfg = cfg.model_copy(
            update={"known_mcp_marker_poc_enabled": True, "sender_source": source()}
        )

        class FakeCollector:
            def __init__(self, *args, **kwargs):
                self.rules = SimpleNamespace(summary=lambda: {"source_blocked": 0})

            def step(self):
                assert server.item["categories"] == ["Personal", "Human"]
                assert server.patch_count == 1  # Applied before the slow source was contacted.

        monkeypatch.setattr("agenttrace_outlook.cli.SenderCollector", FakeCollector)
        monkeypatch.setattr("agenttrace_outlook.cli.certificate_audit", lambda config: object())
    paths = files(tmp_path, store, writer)
    paths[0].write_text(cfg.model_dump_json())
    store.close()
    graph = Graph()
    graph.messages[server.item["id"]] = server.item
    graph.pages["inbox"] = [[{"id": server.item["id"]}]]
    if deny:
        server.mode = "forbidden"
    monkeypatch.setattr(
        "agenttrace_outlook.cli.StateStore", lambda config: StateStore(config, clock=clock)
    )
    monkeypatch.setattr(
        "agenttrace_outlook.cli.certificate_reader", lambda config: MailReader(config, graph)
    )
    monkeypatch.setattr(
        "agenttrace_outlook.cli.certificate_catalog", lambda settings, identity: writer.catalog
    )
    monkeypatch.setattr(
        "agenttrace_outlook.category_application.datetime",
        type("Time", (), {"now": staticmethod(lambda zone: clock())}),
    )
    args = arguments(paths) if apply else ["--config", str(paths[0]), "--dry-run"]
    assert main(args + ["--once"]) == (1 if deny else 0)
    first = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert next(x for x in first if x["event"] == "cycle_completed")["processed"] == 1
    assert server.patch_count == int(apply)
    if apply:
        result = next(x for x in first if x["event"] == "category_result")
        assert result["classification"] == "Human"
        assert result["status"] == ("blocked" if deny else "applied")
        assert "received-one" not in json.dumps(first)
    assert main(args + ["--once"]) == (1 if deny else 0)
    assert server.patch_count == int(apply)
    # Both locks are released after stopping, including error exits.
    with StateStore(cfg, clock=clock):
        ownership = OwnershipStore(writer.catalog.settings)
        ownership.close()


def test_apply_check_is_offline_and_does_not_open_state(tmp_path, monkeypatch, capsys):
    store, writer, server, clock, _, _ = setup(tmp_path)
    paths = files(tmp_path, store, writer)
    server.calls.clear()
    store.close()
    monkeypatch.setattr(
        "agenttrace_outlook.category_application.datetime",
        type("Time", (), {"now": staticmethod(lambda zone: clock())}),
    )

    def unexpected(*args, **kwargs):
        pytest.fail("check must not open state or connect")

    monkeypatch.setattr("agenttrace_outlook.cli.StateStore", unexpected)
    monkeypatch.setattr("agenttrace_outlook.cli.certificate_catalog", unexpected)
    assert main(arguments(paths) + ["--check"]) == 0
    assert json.loads(capsys.readouterr().out)["category_writes"] is False
    assert not server.calls
