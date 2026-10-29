"""Generate fictional local-test signing material and separate database credentials."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ROOT = Path(__file__).resolve().parents[1]
TENANT = "00000000-0000-4000-8000-000000000001"
AUDIENCE = "00000000-0000-4000-8000-000000000002"
CLIENT = "00000000-0000-4000-8000-000000000003"
SUBJECT = "00000000-0000-4000-8000-000000000004"


def prepare() -> None:
    directory = ROOT / "work/local"
    roles = directory / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    roles.chmod(0o700)
    for name in ["api", "attribution", "content", "collector", "ledger"]:
        path = roles / (name + "-password")
        if not path.exists():
            with path.open("x", encoding="utf-8") as output:
                output.write(secrets.token_urlsafe(32))
            path.chmod(0o644)  # Private host directory; non-root read-only container mount.
    key_path = directory / "development-signing-key.pem"
    if not key_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with key_path.open("xb") as output:
            output.write(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
        key_path.chmod(0o600)
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("local_rsa_key_required")
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "local-development", "alg": "RS256", "use": "sig"})
    (directory / "development-jwks.json").write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
    (directory / "development-jwks.json").chmod(0o644)
    settings = {
        "tenant": TENANT,
        "audience": AUDIENCE,
        "allowed_clients": [CLIENT],
        "subjects": {SUBJECT: ["synthetic-mailbox"]},
        "messages": {"synthetic-example": "synthetic-mailbox"},
        "local_jwks_file": "/run/secrets/development_jwks",
    }
    (directory / "development-authorization.json").write_text(
        json.dumps(settings), encoding="utf-8"
    )
    (directory / "development-authorization.json").chmod(0o644)


if __name__ == "__main__":
    prepare()
    print(json.dumps({"development_security": "ready", "keys_are_entra_credentials": False}))
