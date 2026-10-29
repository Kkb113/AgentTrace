"""Pinned Ed25519 signatures over domain-separated canonical records and key IDs."""

import base64
from datetime import datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .canonical import LedgerError, canonical_bytes
from .contracts import SignedEvidence


def signing_bytes(envelope: SignedEvidence) -> bytes:
    return b"AgentTrace/evidence/1.0\x00" + canonical_bytes(
        {"algorithm": envelope.algorithm, "key_ref": envelope.key_ref, "record": envelope.record}
    )


def verify_signature(
    envelope: SignedEvidence,
    public_key: bytes,
    now: datetime,
    valid_from: datetime,
    valid_until: datetime,
) -> None:
    record = envelope.record
    if (
        not valid_from <= record.issued_at < valid_until
        or not record.issued_at <= now < record.expires_at
    ):
        raise LedgerError("evidence_key_or_record_not_current")
    try:
        signature = base64.b64decode(envelope.signature, validate=True)
        if len(signature) != 64:
            raise ValueError
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, signing_bytes(envelope))
    except (InvalidSignature, ValueError):
        raise LedgerError("invalid_evidence_signature") from None
