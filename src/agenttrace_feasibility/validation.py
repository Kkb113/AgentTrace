"""Bounded, strict input handling for untrusted evidence and email exports."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 1000


class InputError(ValueError):
    """An input failed a documented contract; messages contain no raw content."""


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate_json_key")
        result[key] = value
    return result


def read_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise InputError("regular_file_required")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise InputError("input_too_large")
    with path.open("rb") as source:
        data = source.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise InputError("input_too_large")
    return data


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            read_bytes(path),
            object_pairs_hook=_unique_keys,
            parse_constant=lambda _: _invalid_number(),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InputError("invalid_json") from exc


def _invalid_number() -> None:
    raise InputError("non_finite_json_number")


def canonical_bytes(value: Any) -> bytes:
    """This restricted JSON contract is not a claim of general RFC 8785 support."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_fields(value: Any, required: set[str], optional: set[str] | None = None) -> dict:
    if not isinstance(value, dict):
        raise InputError("object_required")
    if not required <= value.keys() or value.keys() - required - (optional or set()):
        raise InputError("unexpected_or_missing_fields")
    return value


def text(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise InputError("bounded_nonempty_string_required")
    return value


def timestamp(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError("invalid_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise InputError("timezone_required")
    return parsed.astimezone(UTC)


def child_path(root: Path, relative: Any) -> Path:
    supplied = Path(text(relative))
    resolved_root = root.resolve()
    resolved = (resolved_root / supplied).resolve()
    if supplied.is_absolute() or not resolved.is_relative_to(resolved_root):
        raise InputError("path_outside_bundle")
    return resolved


def record_list(value: Any) -> list:
    if not isinstance(value, list) or len(value) > MAX_RECORDS:
        raise InputError("bounded_record_list_required")
    return value
