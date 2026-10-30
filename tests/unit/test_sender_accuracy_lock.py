"""Encrypted holdout controls, simulated custody and CLI process end-to-end tests."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from agenttrace_outlook.accuracy_cli import export_development
from agenttrace_outlook.accuracy_io import decode, read, write_new
from agenttrace_outlook.errors import OutlookError
from agenttrace_outlook.evaluation_lock import (
    access_snapshot,
    grant,
    open_once,
    seal,
    verify_access,
)
from tests.sender_accuracy_support import NOW, study


def prepared(tmp_path: Path):
    root = tmp_path / "originals"
    root.mkdir(mode=0o700)
    dataset = study(root)
    key = tmp_path / "keys" / "curator.key"
    key.parent.mkdir(mode=0o700)
    key.write_bytes(bytes(range(32)))
    key.chmod(0o600)
    archive = tmp_path / "frozen" / "study.json"
    seal(
        root,
        dataset,
        archive,
        key,
        NOW,
        developer_principal="fictional_developer",
        control_drill=True,
    )
    return root, dataset, key, archive


def test_encrypted_archive_has_no_plaintext_labels_and_grant_is_single_use(tmp_path: Path) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    raw = read(archive)
    assert b"fictional_curator" not in raw and b"message.eml" not in raw
    permit = grant(archive, key, NOW)
    opened = open_once(archive, permit, key, tmp_path / "receipts", NOW)
    assert opened["metadata"]["access"]["independent_access_verified"] is False
    assert opened["dataset"]["study_ref"] == dataset.study_ref
    with pytest.raises(OutlookError, match="authorization_denied"):
        open_once(archive, grant(archive, key, NOW), key, tmp_path / "receipts", NOW)


@pytest.mark.parametrize("mutation", ["grant_mac", "archive", "wrong_code", "expiry", "wrong_key"])
def test_tampered_study_or_authorization_is_denied(tmp_path: Path, mutation: str) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    permit = grant(archive, key, NOW)
    when = NOW
    if mutation == "grant_mac":
        permit["mac"] = "0" * 64
    elif mutation == "archive":
        archive.write_bytes(read(archive) + b" ")
    elif mutation == "wrong_code":
        permit["record"]["detector_sha256"] = "0" * 64
    elif mutation == "expiry":
        when = NOW + timedelta(hours=2)
    elif mutation == "wrong_key":
        key.write_bytes(b"x" * 32)
    with pytest.raises(OutlookError, match="authorization_denied"):
        open_once(archive, permit, key, tmp_path / "receipts", when)


def test_same_principal_cannot_claim_independent_os_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "originals"
    root.mkdir()
    key = tmp_path / "keys" / "key"
    key.parent.mkdir()
    key.write_bytes(b"x" * 32)
    monkeypatch.setattr(
        "agenttrace_outlook.evaluation_lock.access_snapshot",
        lambda p: {"principal": "developer", "private_access": True},
    )
    with pytest.raises(OutlookError, match="independent_curator_private_access_required"):
        verify_access(root, key, "developer")


def test_broad_acl_cannot_claim_an_independent_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "originals"
    root.mkdir()
    key = tmp_path / "keys" / "key"
    key.parent.mkdir()
    key.write_bytes(b"x" * 32)
    monkeypatch.setattr(
        "agenttrace_outlook.evaluation_lock.access_snapshot",
        lambda p: {"principal": "curator", "private_access": False},
    )
    with pytest.raises(OutlookError, match="independent_curator_private_access_required"):
        verify_access(root, key, "developer")


def test_development_export_contains_no_holdout_cases_or_assets(tmp_path: Path) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    destination = tmp_path / "developer_export"
    export_development(root, dataset, destination, NOW)
    value = json.loads((destination / "dataset.json").read_text())
    assert value["usage"] == "development_export"
    assert all(c["split"] != "evaluation" for c in value["cases"])
    assert not (destination / dataset.cases[-1].input.path).exists()


def test_concurrent_open_consumes_only_one_receipt(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    root, dataset, key, archive = prepared(tmp_path)
    permit = grant(archive, key, NOW)

    def attempt():
        try:
            open_once(archive, permit, key, tmp_path / "receipts", NOW)
            return True
        except OutlookError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(lambda _: attempt(), range(2))) == 1


def test_cli_control_drill_runs_real_process_without_qualifying_accuracy(tmp_path: Path) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    # NOW fixtures are within the permitted source window at the real client date.
    permit_path = tmp_path / "permit.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate-sender-accuracy.py",
            "grant",
            "--archive",
            str(archive),
            "--key",
            str(key),
            "--output",
            str(permit_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout
    output = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate-sender-accuracy.py",
            "evaluate-locked",
            "--archive",
            str(archive),
            "--permit",
            str(permit_path),
            "--key",
            str(key),
            "--receipts",
            str(tmp_path / "receipts"),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout
    report = decode(read(output))
    assert report["control_drill"] and not report["release_accuracy_qualified"]
    assert report["locked_access_verified"] is False
    assert "owner@example.invalid" not in result.stdout and "fictional_curator" not in result.stdout


def test_cli_rejects_ordinary_read_of_locked_manifest_without_leaking_paths(tmp_path: Path) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    manifest = root / "dataset.json"
    write_new(manifest, dataset.model_dump(mode="json"))
    result = subprocess.run(
        [
            sys.executable,
            "scripts/validate-sender-accuracy.py",
            "run",
            "--dataset",
            str(manifest),
            "--split",
            "development",
            "--output",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert str(root) not in result.stdout and "owner@example.invalid" not in result.stdout


def test_authenticated_metadata_tamper_is_rejected_even_with_a_new_grant(tmp_path: Path) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    blob = decode(read(archive))
    blob["metadata"]["expires_at"] = (NOW + timedelta(days=10)).isoformat()
    archive.write_text(json.dumps(blob))
    with pytest.raises(OutlookError, match="authorization_denied"):
        open_once(archive, grant(archive, key, NOW), key, tmp_path / "receipts", NOW)


def test_changed_code_cannot_reuse_an_earlier_frozen_holdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, dataset, key, archive = prepared(tmp_path)
    monkeypatch.setattr("agenttrace_outlook.evaluation_lock.detector_digest", lambda: "f" * 64)
    with pytest.raises(OutlookError, match="authorization_denied"):
        open_once(archive, grant(archive, key, NOW), key, tmp_path / "receipts", NOW)


def test_actual_platform_acl_inspector_executes_without_claiming_separation(tmp_path: Path) -> None:
    value = access_snapshot(tmp_path)
    assert isinstance(value["principal"], str) and value["principal"]
    assert type(value["private_access"]) is bool
