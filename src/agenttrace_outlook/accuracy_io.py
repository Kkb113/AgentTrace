"""Bounded private study I/O, source retention and reproducible code/policy identities."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from agenttrace_feasibility.validation import canonical_bytes

from .accuracy_contracts import AccuracyDataset, Asset
from .errors import OutlookError

MAX_BYTES = 192 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[2]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_path(path: Path) -> Path:
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise OutlookError("study_path_alias_rejected")
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise OutlookError("study_regular_private_file_required")
    return path


def read(path: Path) -> bytes:
    checked_path(path)
    if path.stat().st_size > MAX_BYTES:
        raise OutlookError("study_file_too_large")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise OutlookError("study_file_too_large")
    return data


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise OutlookError("study_duplicate_json_key")
        result[key] = value
    return result


def _invalid(_: str) -> None:
    raise OutlookError("study_nonfinite_number")


def decode(data: bytes) -> Any:
    if len(data) > MAX_BYTES:
        raise OutlookError("study_file_too_large")
    return json.loads(data, object_pairs_hook=_unique, parse_constant=_invalid)


def load_dataset(path: Path) -> AccuracyDataset:
    return AccuracyDataset.model_validate_json(canonical_bytes(decode(read(path))))


def write_new(path: Path, value: Any) -> None:
    checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = canonical_bytes(value) + b"\n"
    if len(data) > MAX_BYTES:
        raise OutlookError("study_file_too_large")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def asset_bytes(root: Path, asset: Asset, now: datetime) -> bytes:
    # Deny access before stat/read/hash, including copies imported from old collections.
    if not asset.collected_at <= now < asset.expires_at:
        raise OutlookError("study_source_outside_retention")
    relative = Path(asset.path)
    path = root / relative
    if relative.is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise OutlookError("study_asset_outside_root")
    data = read(path)
    if digest(data) != asset.sha256:
        raise OutlookError("study_asset_hash_mismatch")
    return data


def policy_digest() -> str:
    return digest(canonical_bytes(decode(read(ROOT / "config/sender-accuracy-policy.json"))))


def detector_digest() -> str:
    result = hashlib.sha256()
    for path in sorted((ROOT / "src/agenttrace_outlook").glob("*.py")):
        data = path.read_bytes().replace(b"\r\n", b"\n")
        result.update(path.name.encode() + b"\0" + str(len(data)).encode() + b"\0" + data)
    for name in (
        "uv.lock",
        "requirements-runtime.txt",
        "requirements-build.txt",
        "scripts/inspect-evaluation-access.ps1",
    ):
        result.update(name.encode() + b"\0" + (ROOT / name).read_bytes().replace(b"\r\n", b"\n"))
    result.update(canonical_bytes(decode(read(ROOT / "config/outlook-detection-policy.json"))))
    return result.hexdigest()
