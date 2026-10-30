"""Generalized coverage and prompt handoff of arbitrary received messages."""

import json

from agenttrace_outlook.config import RuntimeConfig, read_config
from agenttrace_outlook.mail_semantics import sender_snapshot
from agenttrace_outlook.reader import DETAIL_FIELDS, MailReader
from agenttrace_outlook.runner import run_once
from agenttrace_outlook.state import StateStore
from agenttrace_outlook.synchronizer import Synchronizer
from tests.unit.test_outlook_sync import NOW, Graph, config, detail, settle


def test_new_observation_yields_to_classification_before_remaining_fetches(tmp_path):
    graph = Graph()
    graph.messages = {str(i): detail(str(i), subject=f"Arbitrary subject {i}") for i in range(4)}
    graph.pages["inbox"] = [[{"id": mid} for mid in graph.messages]]
    with StateStore(config(tmp_path), clock=lambda: NOW) as store:
        sync = Synchronizer(store, MailReader(store.config, graph))
        for _ in range(10):
            sync.run_cycle()
            if store.summary()["observations"]:
                break
        assert store.summary()["observations"] == 1
        assert sync.state.summary()["sync_pending_items"] == 3
        assert run_once(store) == 1
        settle(sync)
        assert store.summary()["observations"] == 4
        assert store.summary()["decisions"] == 4


def test_subject_is_not_selected_or_part_of_classification_snapshot():
    from agenttrace_outlook.category_endpoint import FIELDS

    raw = detail("any-message")
    before = sender_snapshot(raw)
    raw["subject"] = "Any private text, including AI or Human claims"
    raw["internetMessageHeaders"].append({"name": "Subject", "value": "AI Agent"})
    assert sender_snapshot(raw) == before
    assert "subject" not in DETAIL_FIELDS.split(",")
    assert "subject" not in FIELDS.split(",")
    assert "body" not in DETAIL_FIELDS and "body" not in FIELDS


def test_legacy_test_filters_are_removed_instead_of_controlling_delivery(tmp_path):
    cfg = config(tmp_path / "state")
    value = cfg.model_dump(mode="json")
    value.update(
        synthetic_subject_prefix="never-match",
        synthetic_message_ids=["one-fixed-message"],
        data_boundary="synthetic_only",
    )
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    migrated = read_config(path)
    assert migrated.data_boundary == "mailbox_headers_only"
    assert "synthetic_subject_prefix" not in RuntimeConfig.model_fields
    assert "synthetic_message_ids" not in RuntimeConfig.model_fields
    assert "never-match" not in migrated.model_dump_json()
