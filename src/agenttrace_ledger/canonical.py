"""Project-specific canonical bytes and tenant-keyed fingerprints, never global hashes."""

from __future__ import annotations

import hashlib
import hmac
import json
import unicodedata
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from .contracts import MessageObservation


class LedgerError(ValueError):
    """A fixed safe reason code; no payload in error strings."""


def _primitive(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _primitive(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise LedgerError("naive_evidence_time")
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        if not all(isinstance(k, str) for k in value):
            raise LedgerError("invalid_canonical_key")
        return {k: _primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise LedgerError("unsupported_canonical_value")


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _primitive(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (UnicodeError, TypeError, ValueError):
        raise LedgerError("invalid_canonical_input") from None


def text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def text_sha256(value: str) -> str:
    return hashlib.sha256(text(value).encode()).hexdigest()


def fingerprint(key: bytes, tenant: UUID, domain: str, value: Any) -> str:
    if len(key) != 32:
        raise LedgerError("tenant_fingerprint_key_must_be_256_bits")
    return hmac.new(
        key, canonical_bytes(["agenttrace-ledger-v1", tenant, domain, value]), hashlib.sha256
    ).hexdigest()


def message_material(message: MessageObservation, key: bytes) -> dict[str, Any]:
    body = text(message.body)
    regions = message.regions
    spans: list[dict[str, Any]] = (
        [{"start": 0, "end": len(body), "role": "authored"}]
        if not regions and body
        else [r.model_dump() for r in regions]
    )
    last = 0
    for span in spans:
        if not last <= span["start"] < span["end"] <= len(body):
            raise LedgerError("invalid_or_overlapping_canonical_region")
        last = span["end"]
    recipients = []
    for recipient in message.recipients:
        address = text(recipient.address).strip()
        if address.count("@") != 1 or any(ord(c) < 33 for c in address):
            raise LedgerError("invalid_canonical_recipient")
        local, domain = address.rsplit("@", 1)
        recipients.append((recipient.role, local + "@" + domain.lower()))
    recipients = sorted(set(recipients))

    def digest(domain: str, value: Any) -> str:
        return fingerprint(key, message.tenant_id, domain, value)

    return {
        "canonicalization_version": "mail-text-v1",
        "immutable_digest": digest("identifier:" + message.namespace, message.immutable_id),
        "internet_digest": digest("internet_message_id", message.internet_message_id)
        if message.internet_message_id
        else None,
        "payload_digest": digest("payload", [text(message.subject), body, recipients])
        if message.content_available and message.recipients_complete
        else None,
        "body_digest": digest("content_sha256", text_sha256(body))
        if message.content_available
        else None,
        "content_available": message.content_available,
        "recipients_complete": message.recipients_complete,
        "recipient_digest": digest("recipients", recipients)
        if message.recipients_complete
        else None,
        "transport_digest": digest("transport_sha256", message.transport_bytes_sha256)
        if message.transport_bytes_sha256
        else None,
        "regions": [
            {**r, "digest": digest("content_sha256", text_sha256(body[r["start"] : r["end"]]))}
            for r in spans
        ],
        "body_length": len(body),
    }


def strict_json(data: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise LedgerError("duplicate_evidence_json_key")
            result[key] = value
        return result

    def invalid(_: str) -> None:
        raise LedgerError("nonfinite_evidence_json_number")

    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, ValueError):
        raise LedgerError("invalid_evidence_json") from None
