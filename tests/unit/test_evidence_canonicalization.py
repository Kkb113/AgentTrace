import base64
from datetime import timedelta, timezone
from uuid import uuid4

import pytest

from agenttrace_ledger.canonical import (
    LedgerError,
    canonical_bytes,
    fingerprint,
    message_material,
    strict_json,
)
from agenttrace_ledger.contracts import Recipient
from agenttrace_ledger.signatures import signing_bytes, verify_signature
from agenttrace_ledger.store import utc_now
from tests.ledger_support import observation, send_fact, signed


def test_canonical_transport_and_recipient_semantics_are_explicit():
    first = observation(
        body="Café\r\nHello", recipients=(Recipient(role="to", address="Local@EXAMPLE.invalid"),)
    )
    second = first.model_copy(
        update={"body": "Cafe\u0301\nHello", "transport_bytes_sha256": "1" * 64}
    )
    a, b = message_material(first, bytes(32)), message_material(second, bytes(32))
    assert a["payload_digest"] == b["payload_digest"]
    assert a["transport_digest"] != b["transport_digest"]
    different = first.model_copy(
        update={"recipients": (Recipient(role="cc", address="Local@example.invalid"),)}
    )
    assert message_material(different, bytes(32))["payload_digest"] != a["payload_digest"]
    assert (
        message_material(
            first.model_copy(update={"immutable_id": first.immutable_id.lower()}), bytes(32)
        )["immutable_digest"]
        != a["immutable_digest"]
    )


def test_tenant_keyed_fingerprints_cannot_be_matched_globally():
    tenant = uuid4()
    assert fingerprint(bytes(32), tenant, "body", "Hello") != fingerprint(
        bytes([1]) * 32, tenant, "body", "Hello"
    )
    assert fingerprint(bytes(32), tenant, "body", "Hello") != fingerprint(
        bytes(32), uuid4(), "body", "Hello"
    )


def test_canonical_evidence_normalizes_timezone_and_dictionary_order():
    now = utc_now()
    assert canonical_bytes({"z": now, "a": "x"}) == canonical_bytes(
        {"a": "x", "z": now.astimezone(timezone(timedelta(hours=5, minutes=30)))}
    )


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":'])
def test_ambiguous_evidence_json_is_rejected(payload):
    with pytest.raises(LedgerError):
        strict_json(payload)


def test_signature_binds_key_record_scope_and_expiry():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    message = observation()
    envelope = signed(message, uuid4(), uuid4(), uuid4(), private, send_fact(message))
    now = utc_now()
    verify_signature(
        envelope,
        private.public_key().public_bytes_raw(),
        now,
        now - timedelta(days=1),
        now + timedelta(days=1),
    )
    changed = envelope.model_copy(update={"key_ref": uuid4()})
    with pytest.raises(LedgerError, match="invalid_evidence_signature"):
        verify_signature(
            changed,
            private.public_key().public_bytes_raw(),
            now,
            now - timedelta(days=1),
            now + timedelta(days=1),
        )
    expired = now + timedelta(days=3)
    with pytest.raises(LedgerError, match="not_current"):
        verify_signature(
            envelope,
            private.public_key().public_bytes_raw(),
            expired,
            now - timedelta(days=1),
            expired + timedelta(days=1),
        )
    assert base64.b64decode(envelope.signature) == private.sign(signing_bytes(envelope))


def test_naive_and_unsupported_canonical_values_are_rejected():
    with pytest.raises(LedgerError):
        canonical_bytes(utc_now().replace(tzinfo=None))
    with pytest.raises(LedgerError):
        canonical_bytes({"score": float("nan")})
    assert canonical_bytes(utc_now()).endswith(b'Z"')
