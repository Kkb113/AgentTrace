"""Study integrity and leakage controls with explicitly simulated external records."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from agenttrace_outlook.accuracy import inspect_study, run_study
from agenttrace_outlook.accuracy_contracts import DetectorPacket, review_binding
from agenttrace_outlook.accuracy_io import asset_bytes, decode, digest, load_dataset
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.sender_rules import sha
from tests.sender_accuracy_support import NOW, packet, study, write_asset


def test_simulated_source_reviews_and_disjoint_groups_validate(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    result = inspect_study(tmp_path, dataset, NOW)
    assert result["issues"] == [] and all(not x for x in result["case_issues"].values())
    # This test simulates curator records. It does not create actual independent labels.


@pytest.mark.parametrize(
    "group", ["sender", "workflow", "thread", "template", "source", "independence_cluster"]
)
def test_every_required_group_is_checked_across_splits(tmp_path: Path, group: str) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    first, second, third = dataset.cases
    second = second.model_copy(
        update={"groups": second.groups.model_copy(update={group: getattr(first.groups, group)})}
    )
    result = inspect_study(
        tmp_path, dataset.model_copy(update={"cases": (first, second, third)}), NOW
    )
    assert "group_or_source_leakage_across_splits" in result["issues"]


def test_text_and_near_duplicates_cannot_leak_across_splits(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    first, second, third = dataset.cases
    original = (tmp_path / first.message.path).read_bytes()
    asset = write_asset(tmp_path, second.message.path, original)
    second = second.model_copy(update={"message": asset})
    result = inspect_study(
        tmp_path, dataset.model_copy(update={"cases": (first, second, third)}), NOW
    )
    assert "duplicate_text_across_splits" in result["issues"]


def test_review_of_different_input_cannot_approve_the_detector_packet(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    first, *remaining = dataset.cases
    review = first.reviews[0].model_copy(update={"input_sha256": "0" * 64})
    first = first.model_copy(update={"reviews": (review,)})
    errors = inspect_study(
        tmp_path, dataset.model_copy(update={"cases": (first, *remaining)}), NOW
    )["case_issues"][first.case_ref]
    assert "independent_action_review_missing" in errors
    assert "review_attestation_does_not_match_record" in errors


def test_expired_source_is_denied_before_source_file_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = study(tmp_path)
    asset = dataset.cases[0].input.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})

    def forbidden(*args):
        raise AssertionError("Expired file was accessed")

    monkeypatch.setattr("agenttrace_outlook.accuracy_io.read", forbidden)
    with pytest.raises(OutlookError, match="study_source_outside_retention"):
        asset_bytes(tmp_path, asset, NOW)


def test_path_escape_hash_tamper_and_duplicate_json_keys_reject(tmp_path: Path) -> None:
    dataset = study(tmp_path)
    asset = dataset.cases[0].input
    with pytest.raises(OutlookError, match="outside_root"):
        asset_bytes(tmp_path, asset.model_copy(update={"path": "../escape"}), NOW)
    (tmp_path / asset.path).write_text("tampered")
    with pytest.raises(OutlookError, match="hash_mismatch"):
        asset_bytes(tmp_path, asset, NOW)
    with pytest.raises(OutlookError, match="duplicate_json_key"):
        decode(b'{"actor":1,"actor":2}')


def test_fixture_or_owner_pilot_cannot_pass_independent_accuracy(tmp_path: Path) -> None:
    dataset = study(tmp_path)
    report = run_study(tmp_path, dataset, "evaluation", NOW, locked_access_verified=True)
    assert report["release_accuracy_qualified"] is False
    assert report["windows"]["initial"]["all_paths"]["eligible_messages"] == 0
    assert report["case_count"] == 1


def test_underpowered_independent_shape_remains_pilot_only(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    report = run_study(tmp_path, dataset, "evaluation", NOW, locked_access_verified=True)
    assert report["windows"]["initial"]["all_paths"]["eligible_messages"] == 1
    assert report["release_accuracy_qualified"] is False
    assert report["windows"]["initial"]["by_population"]["enrolled_claude_poc"]["G2"] is False


def test_late_outcome_does_not_overwrite_missed_initial_window(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    *before, last = dataset.cases
    raw = json.loads((tmp_path / last.input.path).read_text())
    raw["frames"][0]["source"] = None
    new = write_asset(tmp_path, last.input.path, json.dumps(raw).encode())
    last = last.model_copy(update={"input": new})
    dataset = dataset.model_copy(update={"cases": (*before, last)})
    report = run_study(tmp_path, dataset, "evaluation", NOW, locked_access_verified=True)
    assert report["rows"][0]["category"] == "Unknown"
    assert report["rows"][1]["category"] == "AI Agent"
    assert (
        report["release_accuracy_qualified"] is False
    )  # Source-changing edit also invalidates review.


def test_ordinary_runner_cannot_select_locked_evaluation(tmp_path: Path) -> None:
    dataset = study(tmp_path)
    with pytest.raises(OutlookError, match="curator_release"):
        run_study(tmp_path, dataset, "evaluation", NOW)


def test_future_deadline_is_not_scored_as_observed_accuracy(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    *before, last = dataset.cases
    fresh = packet(NOW - timedelta(minutes=10), agent=True)
    asset = write_asset(tmp_path, last.input.path, fresh.model_dump_json().encode())
    last = last.model_copy(update={"input": asset})
    dataset = dataset.model_copy(update={"cases": (*before, last)})
    report = run_study(
        tmp_path,
        dataset,
        "evaluation",
        NOW,
        locked_access_verified=True,
    )
    assert all(not r["accuracy_eligible"] for r in report["rows"])
    assert "window_not_mature" in report["rows"][0]["quarantine"]


def test_detector_projection_cannot_receive_labels_subject_body_or_case_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = study(tmp_path)
    calls = []
    from agenttrace_outlook.accuracy_replay import replay

    def observe(packet, enrollment, at):
        assert isinstance(packet, DetectorPacket)
        projected = packet.model_dump_json()
        assert "fictional_curator" not in projected and "sample_c" not in projected
        assert '"actor"' not in projected and '"reviews"' not in projected
        assert '"body"' not in projected and '"subject"' not in projected
        calls.append(packet)
        return replay(packet, enrollment, at)

    monkeypatch.setattr("agenttrace_outlook.accuracy.replay", observe)
    run_study(tmp_path, dataset, "evaluation", NOW, locked_access_verified=True)
    assert len(calls) == 2


def test_actual_action_truth_cannot_be_changed_by_switching_case_labels(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    *before, last = dataset.cases
    original = run_study(tmp_path, dataset, "evaluation", NOW, locked_access_verified=True)
    last = last.model_copy(update={"actor": "human"})
    altered = run_study(
        tmp_path,
        dataset.model_copy(update={"cases": (*before, last)}),
        "evaluation",
        NOW,
        locked_access_verified=True,
    )
    assert original["rows"][0]["category"] == altered["rows"][0]["category"] == "AI Agent"
    assert "label_does_not_match_review" in altered["rows"][0]["quarantine"]


def test_unavailable_header_inspection_keeps_reviewed_agent_in_recall_denominator(
    tmp_path: Path,
) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    *before, last = dataset.cases
    raw = json.loads((tmp_path / last.input.path).read_text())
    for frame in raw["frames"]:
        frame["snapshot"]["internetMessageHeaders"] = None
    raw["observation"]["source_digest"] = sha(raw["frames"][0]["snapshot"])
    asset = write_asset(tmp_path, last.input.path, json.dumps(raw).encode())
    last = last.model_copy(update={"input": asset})
    review = last.reviews[0].model_copy(
        update={"input_sha256": asset.sha256, "case_sha256": review_binding(last)}
    )
    attestation = write_asset(
        tmp_path,
        review.attestation.path,
        json.dumps(review.model_dump(mode="json", exclude={"attestation"})).encode(),
    )
    last = last.model_copy(
        update={"reviews": (review.model_copy(update={"attestation": attestation}),)}
    )
    report = run_study(
        tmp_path,
        dataset.model_copy(update={"cases": (*before, last)}),
        "evaluation",
        NOW,
        locked_access_verified=True,
    )
    actual = report["windows"]["initial"]["all_paths"]
    assert actual["eligible_messages"] == 1 and actual["recall"] == 0
    assert actual["positive_misses_including_unknown_and_human_label"] == 1


def test_dataset_schema_roundtrip_is_strict(tmp_path: Path) -> None:
    dataset = study(tmp_path)
    path = tmp_path / "dataset.json"
    path.write_text(dataset.model_dump_json())
    assert load_dataset(path) == dataset
    assert digest(path.read_bytes())


def test_ordinary_automation_coverage_cannot_be_faked_with_a_human_family_tag(
    tmp_path: Path,
) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    first, *others = dataset.cases
    first = first.model_copy(update={"families": ("ordinary_automation",)})
    result = inspect_study(tmp_path, dataset.model_copy(update={"cases": (first, *others)}), NOW)
    assert "scenario_family_conflicts_with_action_truth" in result["case_issues"][first.case_ref]


def test_supported_route_cannot_be_relabelled_after_review_to_hide_a_miss(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    *before, last = dataset.cases
    last = last.model_copy(update={"source_family": "browser_agent", "supported_agent_path": False})
    result = inspect_study(tmp_path, dataset.model_copy(update={"cases": (*before, last)}), NOW)
    assert "independent_action_review_missing" in result["case_issues"][last.case_ref]


def test_repeated_provider_message_identity_is_not_an_independent_split(tmp_path: Path) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    first, second, third = dataset.cases
    raw = json.loads((tmp_path / second.input.path).read_text())
    raw["observation"]["message_id"] = "provider_0"
    raw["observation"]["scope"] = json.loads((tmp_path / first.input.path).read_text())[
        "observation"
    ]["scope"]
    asset = write_asset(tmp_path, second.input.path, json.dumps(raw).encode())
    second = second.model_copy(update={"input": asset})
    result = inspect_study(
        tmp_path, dataset.model_copy(update={"cases": (first, second, third)}), NOW
    )
    assert "group_or_source_leakage_across_splits" in result["issues"]


def test_observed_sender_cannot_be_hidden_by_declaring_different_sender_groups(
    tmp_path: Path,
) -> None:
    dataset = study(tmp_path, simulated_independent=True)
    first, second, third = dataset.cases
    raw = json.loads((tmp_path / second.input.path).read_text())
    for frame in raw["frames"]:
        frame["snapshot"]["internetMessageHeaders"][0]["value"] = "owner_0@example.invalid"
    asset = write_asset(tmp_path, second.input.path, json.dumps(raw).encode())
    second = second.model_copy(update={"input": asset})
    result = inspect_study(
        tmp_path, dataset.model_copy(update={"cases": (first, second, third)}), NOW
    )
    assert "group_or_source_leakage_across_splits" in result["issues"]
