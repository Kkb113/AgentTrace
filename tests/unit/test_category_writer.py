"""Decision-to-mailbox writer drills, including crash/ambiguity, conflicts and user edits."""

from __future__ import annotations

import copy
import json
import sqlite3
from datetime import timedelta
from urllib.parse import unquote, urlsplit

import pytest

from agenttrace_ingestion.contracts import IngestionError
from agenttrace_outlook.category_catalog import CategoryCatalog
from agenttrace_outlook.category_write_contracts import CategoryEndpointQualification
from agenttrace_outlook.category_writer import CategoryWriter
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.mail_semantics import sender_snapshot
from agenttrace_outlook.reader import MailReader
from agenttrace_outlook.sender_rules import sha
from agenttrace_outlook.state import SCHEMA_FOUR, SCHEMA_FOUR_DIGEST, StateStore
from agenttrace_outlook.synchronizer import Synchronizer
from tests.unit.test_outlook_categories import provisioned
from tests.unit.test_outlook_sync import Graph, config, detail, requeue, settle
from tests.unit.test_sender_rules import NOW, snapshot


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self):
        self.now += timedelta(seconds=5)


class Server:
    def __init__(self, message, definitions):
        self.item = copy.deepcopy(message)
        self.definitions = definitions
        self.version = 1
        self.patch_count = 0
        self.calls = []
        self.mode = None
        self.fail_read = False
        self.readback_failure = False
        self.response_etag_missing = False
        self.bad_precondition = False

    def edit(self, categories):
        self.item["categories"] = categories
        self.version += 1

    def current(self):
        return copy.deepcopy(
            {**self.item, "@odata.etag": f'W/"v{self.version}"', "changeKey": f"v{self.version}"}
        )

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        if "masterCategories" in url:
            return {"value": copy.deepcopy(self.definitions)}
        if unquote(urlsplit(url).path.split("/messages/")[-1]) != self.item["id"]:
            raise IngestionError("source_item_not_found")
        if method == "GET":
            if self.fail_read:
                raise IngestionError("source_network_unavailable", retryable=True, retry_after=1)
            return self.current()
        assert method == "PATCH" and set(kwargs["body"]) == {"categories"}
        self.patch_count += 1
        mode, self.mode = self.mode, None
        if mode == "user_conflict":
            name = (
                "Later personal"
                if "Later personal" not in self.item["categories"]
                else f"Later personal {self.version}"
            )
            self.edit(self.item["categories"] + [name])
        if mode == "semantic_conflict":
            self.item["internetMessageId"] = "<changed@example.invalid>"
            self.version += 1
        if (
            not self.bad_precondition
            and kwargs["headers"]["If-Match"] != self.current()["@odata.etag"]
        ):
            raise IngestionError("source_version_changed")
        if mode == "timeout_before":
            raise IngestionError("source_network_unavailable", retryable=True, retry_after=1)
        if mode == "forbidden":
            raise IngestionError("source_access_denied")
        if mode == "crash_before":
            raise SystemExit(19)
        self.edit(kwargs["body"]["categories"])
        response = self.current()
        if mode == "timeout_after":
            raise IngestionError("source_network_unavailable", retryable=True, retry_after=1)
        if mode == "crash_after":
            raise SystemExit(19)
        if mode == "edit_after":
            self.edit(self.item["categories"] + ["Later personal"])
        if mode == "moved_after":
            self.item["parentFolderId"] = "sentitems"
            self.version += 1
        if self.readback_failure:
            self.fail_read = True
        if self.response_etag_missing:
            response.pop("@odata.etag")
        return response


def setup(tmp_path, raw=None):
    settings, registry, definitions = provisioned(tmp_path / "ownership")
    cfg = config(tmp_path / "state")
    clock = Clock()
    raw = raw or snapshot()
    item = detail("received-one", **raw, isRead=False, categories=["Personal"])
    graph = Graph()
    graph.messages[item["id"]] = item
    graph.pages["inbox"] = [[{"id": item["id"]}]]
    store = StateStore(cfg, clock=clock)
    sync = Synchronizer(store, MailReader(cfg, graph))
    settle(sync)
    server = Server(item, definitions.rows)
    catalog = CategoryCatalog(settings, server, identity="writer")
    qualification = CategoryEndpointQualification(
        scope=cfg.scope,
        writer_client_id=settings.writer_identity.client_id,
        checked_at=clock(),
        expires_at=clock() + timedelta(days=7),
        probe_reference_sha256="a" * 64,
        current_conditional_patch_verified=True,
        provider_version_changed=True,
        stale_conditional_patch_rejected=True,
        category_membership_preserved=True,
    )
    writer = CategoryWriter(store, catalog, registry, qualification)
    identity = writer.plan(item["id"])[0]
    return store, writer, server, clock, identity, sync


def test_apply_is_owned_merge_readback_and_duplicate_idempotent(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        assert writer.step(identity)["status"] == "applied"
        assert server.item["categories"] == ["Personal", "Human-capable"]
        assert server.item["isRead"] is False
        assert writer.plan(server.item["id"]) == [identity]
        assert writer.plan() == []
        assert writer.step(identity)["status"] == "applied"
        assert server.patch_count == 1
        assert writer.verify(identity)["classification_evidence_current"]
        assert store.db.execute("SELECT count(*) FROM category_attempts").fetchone()[0] == 1
    finally:
        store.close()


def test_stale_etag_remerges_later_unrelated_user_category(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.mode = "user_conflict"
        assert writer.step(identity)["status"] == "pending"
        assert server.item["categories"] == ["Personal", "Later personal"]
        clock.advance()
        assert writer.step(identity)["status"] == "applied"
        assert server.item["categories"] == ["Personal", "Later personal", "Human-capable"]
    finally:
        store.close()


@pytest.mark.parametrize(
    "mode,expected,patches",
    [
        ("timeout_before", "applied", 2),
        ("timeout_after", "reconciled", 1),
        ("crash_before", "applied", 2),
        ("crash_after", "reconciled", 1),
    ],
)
def test_restart_recovers_prepared_or_ambiguous_writes(tmp_path, mode, expected, patches):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    cfg, catalog, registry, qualification = (
        store.config,
        writer.catalog,
        writer.registry,
        writer.qualification,
    )
    try:
        server.mode = mode
        if mode.startswith("crash"):
            with pytest.raises(SystemExit):
                writer.step(identity)
        else:
            assert writer.step(identity)["status"] == "uncertain"
    finally:
        store.close()
    clock.advance()
    with StateStore(cfg, clock=clock) as restarted:
        worker = CategoryWriter(restarted, catalog, registry, qualification)
        assert worker.step(identity)["status"] == expected
        assert server.patch_count == patches
        if expected == "reconciled":
            with pytest.raises(OutlookError, match="attributed_apply"):
                worker.request_rollback(identity)


def test_crash_after_response_journal_recovers_attributed_apply_without_repatch(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.readback_failure = True
        assert writer.step(identity)["status"] == "uncertain"
        server.fail_read = False
        clock.advance()
        assert writer.step(identity)["status"] == "applied"
        assert server.patch_count == 1
    finally:
        store.close()


def test_uncertain_outcome_followed_by_user_edit_is_blocked(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.mode = "timeout_after"
        writer.step(identity)
        server.edit(server.item["categories"] + ["User later"])
        clock.advance()
        assert writer.step(identity)["status"] == "blocked"
        assert "User later" in server.item["categories"]
        assert server.patch_count == 1
    finally:
        store.close()


def test_missing_response_receipt_never_claims_attributed_success(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.response_etag_missing = True
        assert writer.step(identity)["status"] == "reconciled"
        with pytest.raises(OutlookError):
            writer.request_rollback(identity)
    finally:
        store.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "live_header",
        "source",
        "expired",
        "experimental",
        "decision_version",
        "definition",
        "excluded_folder",
        "qualification",
        "no_qualification",
    ],
)
def test_unsafe_or_stale_inputs_cannot_write(tmp_path, mutation):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        if mutation == "live_header":
            server.item["internetMessageId"] = "<changed@example.invalid>"
        if mutation == "source":
            source = {
                "status": "conflicting",
                "observed_version": json.loads(writer.row(identity)["observation"])[
                    "source_version"
                ],
                "expires_at": clock().timestamp() + 600,
                "evidence_refs": [],
            }
            store.db.execute("UPDATE rule_sources SET payload=?", (json.dumps(source),))
        if mutation == "expired":
            decision = json.loads(writer.row(identity)["decision"])
            decision["decided_at"] = (clock() - timedelta(minutes=2)).isoformat()
            decision["expires_at"] = (clock() - timedelta(minutes=1)).isoformat()
            store.db.execute("UPDATE decisions SET payload=?", (json.dumps(decision),))
        if mutation == "experimental":
            decision = json.loads(writer.row(identity)["decision"])
            decision["basis"] = "experimental"
            store.db.execute("UPDATE decisions SET payload=?", (json.dumps(decision),))
        if mutation == "decision_version":
            store.db.execute("UPDATE messages SET decision_version=decision_version+1")
        if mutation == "definition":
            server.definitions[0]["id"] = "replacement"
        if mutation == "excluded_folder":
            server.item["parentFolderId"] = "sentitems"
        if mutation == "qualification":
            writer.qualification = writer.qualification.model_copy(
                update={"expires_at": clock() - timedelta(seconds=1)}
            )
        if mutation == "no_qualification":
            writer.qualification = None
        assert writer.step(identity)["status"] in {"blocked", "superseded"}
        assert server.patch_count == 0
    finally:
        store.close()


def test_semantic_edit_during_conflict_never_receives_old_verdict(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.mode = "semantic_conflict"
        assert writer.step(identity)["status"] == "pending"
        clock.advance()
        assert writer.step(identity)["status"] == "blocked"
        assert server.patch_count == 1
    finally:
        store.close()


def test_existing_identical_label_is_unchanged_and_not_rollback_owned(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.edit(["Personal", "Human-capable"])
        assert writer.step(identity)["status"] == "unchanged"
        assert server.patch_count == 0
        with pytest.raises(OutlookError):
            writer.request_rollback(identity)
    finally:
        store.close()


def test_successful_rollback_removes_only_proven_added_label(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        writer.step(identity)
        writer.request_rollback(identity)
        assert writer.step(identity)["status"] == "rolled_back"
        assert server.item["categories"] == ["Personal"]
        writer.request_rollback(identity)
        assert writer.step(identity)["status"] == "rolled_back"
        assert server.patch_count == 2
    finally:
        store.close()


@pytest.mark.parametrize("later", ["unrelated", "same_label_readded", "removed", "read_state"])
def test_rollback_refuses_any_later_user_edit_without_overwriting_it(tmp_path, later):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        writer.step(identity)
        current = server.item["categories"][:]
        if later == "unrelated":
            server.edit(current + ["New user category"])
        if later == "same_label_readded":
            server.edit(["Personal"])
            server.edit(current)
        if later == "removed":
            server.edit(["Personal"])
        if later == "read_state":
            server.item["isRead"] = True
            server.version += 1
        before = server.current()
        writer.request_rollback(identity)
        assert writer.step(identity)["status"] == "rollback_blocked"
        assert server.current() == before and server.patch_count == 1
    finally:
        store.close()


def test_category_only_delta_does_not_repredict_or_create_new_intent(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        writer.step(identity)
        before = store.db.execute("SELECT count(*) FROM decisions").fetchone()[0]
        sync.reader._transport.messages["received-one"] = server.current()
        requeue(sync, "received-one")
        settle(sync)
        assert store.db.execute("SELECT count(*) FROM decisions").fetchone()[0] == before
        assert writer.plan("received-one") == [identity]
        writer.step(identity)
        assert server.patch_count == 1
    finally:
        store.close()


def test_endpoint_qualification_requires_actual_stale_rejection(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        receipt = writer.endpoint.qualify("received-one", clock())
        receipt.require_current(writer.catalog.settings, clock())
        assert server.item["categories"] == ["Personal"]
        server.bad_precondition = True
        with pytest.raises(OutlookError, match="ignores_conditional"):
            writer.endpoint.qualify("received-one", clock())
    finally:
        store.close()


def test_version_four_database_migrates_with_existing_metadata_intact(tmp_path):
    cfg = config(tmp_path)
    db = sqlite3.connect(tmp_path / "runtime.sqlite3")
    for statement in SCHEMA_FOUR:
        db.execute(statement)
    db.executemany(
        "INSERT INTO metadata VALUES (?,?)",
        [
            ("scope", cfg.scope.model_dump_json()),
            ("schema_digest", SCHEMA_FOUR_DIGEST),
            ("activation_utc", NOW.isoformat()),
        ],
    )
    db.execute("PRAGMA user_version=4")
    db.commit()
    db.close()
    with StateStore(cfg, clock=lambda: NOW) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert store.db.execute("SELECT count(*) FROM category_intents").fetchone()[0] == 0


def test_canonical_semantics_ignore_read_state_categories_and_provider_versions():
    item = detail("one")
    digest = sha(sender_snapshot(item)[0])
    item.update(categories=["AI Agent"], isRead=True, changeKey="new")
    assert sha(sender_snapshot(item)[0]) == digest


def test_cli_missing_inputs_remain_sanitized(tmp_path, capsys):
    from agenttrace_outlook.category_write_cli import main

    assert (
        main(
            ["apply", "--settings", str(tmp_path / "missing"), "--output", str(tmp_path / "result")]
        )
        == 2
    )
    assert str(tmp_path) not in capsys.readouterr().out


def test_unknown_is_a_real_separate_verdict_and_replaces_only_owned_labels(tmp_path):
    raw = snapshot()
    raw["internetMessageHeaders"].append({"name": "x-ai-generated", "value": "mcp-office365"})
    store, writer, server, clock, identity, sync = setup(tmp_path, raw)
    try:
        server.edit(["Personal", "AI Agent", "Human-capable"])
        result = writer.step(identity)
        assert result["status"] == "applied" and result["write_attributed"]
        assert server.item["categories"] == ["Personal", "Unknown"]
        assert writer.verify(identity)["classification_evidence_current"]
    finally:
        store.close()


@pytest.mark.parametrize("mode", ["timeout_before", "timeout_after", "crash_before", "crash_after"])
def test_rollback_interruption_recovers_without_readding_any_label(tmp_path, mode):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        writer.step(identity)
        writer.request_rollback(identity)
        server.mode = mode
        if mode.startswith("crash"):
            with pytest.raises(SystemExit):
                writer.step(identity)
        else:
            assert writer.step(identity)["status"] == "uncertain"
        clock.advance()
        assert writer.step(identity)["status"] == "rolled_back"
        assert server.item["categories"] == ["Personal"]
    finally:
        store.close()


def test_bounded_conflicts_do_not_spin_or_claim_success(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        for _ in range(store.config.max_attempts):
            server.mode = "user_conflict"
            assert writer.step(identity)["status"] == "pending"
            clock.advance()
        assert writer.step(identity)["status"] == "blocked"
        assert server.patch_count == store.config.max_attempts
    finally:
        store.close()


def test_outside_scope_reference_and_deleted_item_are_never_writes(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        with pytest.raises(OutlookError):
            writer.endpoint.read("../other?x=1")
        server.item["id"] = "deleted-item"
        assert writer.step(identity)["status"] == "blocked"
        assert server.patch_count == 0
    finally:
        store.close()


def test_writer_credential_cannot_be_the_read_collector(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        catalog = writer.catalog
        catalog.settings = catalog.settings.model_copy(
            update={"writer_identity": store.config.reader_identity}
        )
        with pytest.raises(OutlookError, match="separate_scoped"):
            CategoryWriter(store, catalog, writer.registry, writer.qualification)
    finally:
        store.close()


def test_unavailable_source_explanation_windows_reassess_once_without_message_edits(tmp_path):
    from agenttrace_outlook.runner import run_once

    store, writer, server, clock, identity, sync = setup(tmp_path)
    cfg = store.config
    original = store.db.execute("SELECT count(*) FROM decisions").fetchone()[0]
    store.close()
    for age, reason in [
        (timedelta(hours=2), "initial_evidence_window_closed"),
        (timedelta(hours=25), "late_observation_window_closed"),
    ]:
        clock.now = NOW + age
        with StateStore(cfg, clock=clock) as reopened:
            assert run_once(reopened) == 1
            current = json.loads(
                reopened.db.execute(
                    "SELECT payload FROM decisions ORDER BY id DESC LIMIT 1"
                ).fetchone()[0]
            )
            assert reason in current["reason_codes"]
            assert current["category"] == "Human-capable"
            count = reopened.db.execute("SELECT count(*) FROM decisions").fetchone()[0]
            assert count == original + 1
            assert run_once(reopened) == 0
            original = count


def test_explicit_retry_after_fixed_denial_still_uses_current_gates(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.mode = "forbidden"
        assert writer.step(identity)["status"] == "blocked"
        writer.request_retry(identity)
        assert writer.step(identity)["status"] == "applied"
        with pytest.raises(OutlookError, match="unfinished_intent"):
            writer.request_retry(identity)
    finally:
        store.close()


def test_explicit_retry_cannot_bypass_rollback_user_edit_protection(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        writer.step(identity)
        server.edit(server.item["categories"] + ["Later user edit"])
        writer.request_rollback(identity)
        assert writer.step(identity)["status"] == "rollback_blocked"
        writer.request_retry(identity)
        assert writer.step(identity)["status"] == "rollback_blocked"
        assert server.patch_count == 1 and "Later user edit" in server.item["categories"]
    finally:
        store.close()


def test_move_out_of_receiving_scope_during_write_is_not_success(tmp_path):
    store, writer, server, clock, identity, sync = setup(tmp_path)
    try:
        server.mode = "moved_after"
        result = writer.step(identity)
        assert result["status"] == "uncertain" and not result["write_attributed"]
        clock.advance()
        assert writer.step(identity)["status"] == "uncertain"
        assert server.patch_count == 1
    finally:
        store.close()
