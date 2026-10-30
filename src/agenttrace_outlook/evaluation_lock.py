"""Curator-only encrypted studies, real OS access checks and one-use code-bound grants.

The curator and OS administrators are trusted. A same-operator control drill is
explicitly unqualified and cannot establish independent holdout access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from agenttrace_feasibility.validation import canonical_bytes, timestamp

from .accuracy import inspect_study
from .accuracy_contracts import AccuracyDataset
from .accuracy_io import (
    ROOT,
    asset_bytes,
    decode,
    detector_digest,
    digest,
    policy_digest,
    read,
    write_new,
)
from .errors import OutlookError

DOMAIN = b"AgentTrace/sender-accuracy/curator/v1\0"


def access_snapshot(path: Path) -> dict[str, Any]:
    if os.name == "nt":
        result = subprocess.run(
            [
                "pwsh.exe",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(ROOT / "scripts/inspect-evaluation-access.ps1"),
                "-Path",
                str(path.resolve()),
            ],
            capture_output=True,
            timeout=20,
            shell=False,
            check=False,
        )
        if result.returncode or len(result.stdout) > 8192:
            raise OutlookError("curator_access_inspection_failed")
        value: dict[str, Any] = decode(result.stdout)
        return value
    info = path.stat()
    principal = str(getattr(os, "geteuid")())
    return {
        "principal": principal,
        "owner": str(info.st_uid),
        "private_access": str(info.st_uid) == principal and not info.st_mode & 0o077,
    }


def verify_access(root: Path, key_path: Path, developer_principal: str) -> dict[str, Any]:
    if key_path.resolve().is_relative_to(root.resolve()):
        raise OutlookError("curator_key_must_be_outside_dataset")
    paths = (root, key_path, key_path.parent)
    evidence = [access_snapshot(p) for p in paths]
    principal = evidence[0].get("principal")
    if (
        not developer_principal
        or principal == developer_principal
        or any(
            row.get("principal") != principal or row.get("private_access") is not True
            for row in evidence
        )
    ):
        raise OutlookError("independent_curator_private_access_required")
    return {
        "principal": principal,
        "developer_principal": developer_principal,
        "os_access_evidence": evidence,
        "independent_access_verified": True,
    }


def _key(path: Path) -> bytes:
    key = read(path)
    if len(key) != 32:
        raise OutlookError("curator_key_length_invalid")
    return key


def seal(
    root: Path,
    dataset: AccuracyDataset,
    archive: Path,
    key_path: Path,
    now: datetime,
    *,
    developer_principal: str,
    control_drill: bool = False,
) -> dict[str, Any]:
    if dataset.usage != "curator_study":
        raise OutlookError("curator_full_study_required")
    inspection = inspect_study(root, dataset, now)
    if dataset.detector_sha256 != detector_digest() or dataset.policy_sha256 != policy_digest():
        raise OutlookError("study_freeze_mismatch")
    access = (
        {"principal": "control_drill", "independent_access_verified": False}
        if control_drill
        else verify_access(root, key_path, developer_principal)
    )
    assets = {}
    expires = now + timedelta(days=7)
    for case in dataset.cases:
        for asset in (
            case.input,
            case.action,
            case.rights,
            *[r.attestation for r in case.reviews],
            *([case.message] if case.message else []),
        ):
            data = asset_bytes(root, asset, now)
            assets[asset.path] = base64.b64encode(data).decode()
            expires = min(expires, asset.expires_at)
    metadata = {
        "schema_version": "1.0",
        "study_ref": dataset.study_ref,
        "dataset_sha256": digest(canonical_bytes(dataset.model_dump(mode="json"))),
        "detector_sha256": detector_digest(),
        "policy_sha256": policy_digest(),
        "expires_at": expires.isoformat(),
        "sealed_at": now.isoformat(),
        "access": access,
        "control_drill": control_drill,
        "curation_issues": inspection["issues"],
    }
    plaintext = canonical_bytes({"dataset": dataset.model_dump(mode="json"), "assets": assets})
    if len(plaintext) > 128 * 1024 * 1024:
        raise OutlookError("frozen_study_budget_exceeded")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key(key_path)).encrypt(
        nonce, plaintext, DOMAIN + canonical_bytes(metadata)
    )
    write_new(
        archive,
        {
            "metadata": metadata,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        },
    )
    return metadata


def grant(archive: Path, key_path: Path, now: datetime) -> dict[str, Any]:
    # Authorization is signed for this exact archive/code/policy, not a mutable path.
    record = {
        "archive_sha256": digest(read(archive)),
        "detector_sha256": detector_digest(),
        "policy_sha256": policy_digest(),
        "issued_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "nonce": secrets.token_hex(16),
    }
    return {
        "record": record,
        "mac": hmac.new(
            _key(key_path), DOMAIN + canonical_bytes(record), hashlib.sha256
        ).hexdigest(),
    }


def open_once(
    archive: Path, permit: dict[str, Any], key_path: Path, receipts: Path, now: datetime
) -> dict[str, Any]:
    try:
        key = _key(key_path)
        record = permit["record"]
        if set(permit) != {"record", "mac"} or set(record) != {
            "archive_sha256",
            "detector_sha256",
            "policy_sha256",
            "issued_at",
            "expires_at",
            "nonce",
        }:
            raise ValueError
        expected = hmac.new(key, DOMAIN + canonical_bytes(record), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, permit["mac"]):
            raise ValueError
        if (
            record["archive_sha256"] != digest(read(archive))
            or record["detector_sha256"] != detector_digest()
            or record["policy_sha256"] != policy_digest()
            or not timestamp(record["issued_at"])
            <= now
            < timestamp(record["expires_at"])
            <= timestamp(record["issued_at"]) + timedelta(hours=1)
        ):
            raise ValueError
        value = decode(read(archive))
        metadata = value["metadata"]
        if (
            timestamp(metadata["expires_at"]) <= now
            or metadata["detector_sha256"] != detector_digest()
            or metadata["policy_sha256"] != policy_digest()
        ):
            raise ValueError
        if metadata["access"]["independent_access_verified"]:
            access = verify_access(
                archive.parent, key_path, metadata["access"]["developer_principal"]
            )
            if access["principal"] != metadata["access"]["principal"]:
                raise ValueError
        plaintext = AESGCM(key).decrypt(
            base64.b64decode(value["nonce"], validate=True),
            base64.b64decode(value["ciphertext"], validate=True),
            DOMAIN + canonical_bytes(metadata),
        )
        result: dict[str, Any] = decode(plaintext)
        if digest(canonical_bytes(result["dataset"])) != metadata["dataset_sha256"]:
            raise ValueError
        # One evaluation per frozen dataset, even if a new permit or archive is made.
        # The curator owns this receipt directory; deleting it breaks the audit boundary.
        write_new(
            receipts / (metadata["dataset_sha256"] + ".json"),
            {
                "consumed_at": now.isoformat(),
                "archive_sha256": record["archive_sha256"],
                "detector_sha256": detector_digest(),
            },
        )
        result["metadata"] = metadata
        return result
    except (KeyError, TypeError, ValueError, InvalidTag, FileExistsError):
        raise OutlookError("locked_study_authorization_denied") from None
