"""Authenticated encryption for cursors/raw snapshots and scoped inference capsules."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import datetime
from typing import Any
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .contracts import IngestionError


class EvidenceCipher:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("ingestion_encryption_key_must_be_256_bits")
        self._key = key

    def reference(self, *parts: str) -> UUID:
        value = hmac.new(
            self._key, json.dumps(parts, separators=(",", ":")).encode(), hashlib.sha256
        ).digest()
        return UUID(bytes=value[:16], version=5)

    def digest(self, value: bytes) -> str:
        return hmac.new(self._key, value, hashlib.sha256).hexdigest()

    def seal(self, value: dict[str, Any], *, context: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(self._key).encrypt(
            nonce,
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(),
            context.encode(),
        )

    def open(self, value: bytes, *, context: str) -> dict[str, Any]:
        try:
            result: dict[str, Any] = json.loads(
                AESGCM(self._key).decrypt(value[:12], value[12:], context.encode())
            )
            if not isinstance(result, dict):
                raise ValueError
            return result
        except Exception:
            raise IngestionError("protected_record_invalid") from None


def seal_content(
    value: dict[str, Any], public_key: rsa.RSAPublicKey, *, version_ref: UUID, expires_at: datetime
) -> bytes:
    key, nonce = os.urandom(32), os.urandom(12)
    context = str(version_ref) + ":" + expires_at.isoformat()
    encrypted = AESGCM(key).encrypt(
        nonce,
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(),
        context.encode(),
    )
    wrapped = public_key.encrypt(
        key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return json.dumps(
        {
            "version_ref": str(version_ref),
            "expires_at": expires_at.isoformat(),
            "key": base64.b64encode(wrapped).decode(),
            "value": base64.b64encode(nonce + encrypted).decode(),
        }
    ).encode()


def open_content(
    value: bytes,
    private_key: rsa.RSAPrivateKey,
    *,
    version_ref: UUID,
    expires_at: datetime,
    now: datetime,
) -> dict[str, Any]:
    if now >= expires_at:
        raise IngestionError("content_input_expired")
    try:
        envelope = json.loads(value)
        if (
            envelope["version_ref"] != str(version_ref)
            or envelope["expires_at"] != expires_at.isoformat()
        ):
            raise ValueError
        key = private_key.decrypt(
            base64.b64decode(envelope["key"], validate=True),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        data = base64.b64decode(envelope["value"], validate=True)
        result: dict[str, Any] = json.loads(
            AESGCM(key).decrypt(
                data[:12], data[12:], (str(version_ref) + ":" + expires_at.isoformat()).encode()
            )
        )
        return result
    except Exception:
        raise IngestionError("content_input_invalid") from None
