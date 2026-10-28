"""Integration-only fictional access tokens, generated under ignored local storage."""

import json
import time
from dataclasses import replace
from pathlib import Path

import jwt

from agenttrace_foundation.authorization import AuthorizationPolicy

ROOT = Path(__file__).resolve().parents[1]


def development_policy():
    policy = AuthorizationPolicy.load(
        ROOT / "work/local/development-authorization.json", local_synthetic=True
    )
    return replace(policy, local_jwks_file=ROOT / "work/local/development-jwks.json")


def development_token(**overrides):
    config = json.loads((ROOT / "work/local/development-authorization.json").read_text())
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{config['tenant']}/v2.0",
        "aud": config["audience"],
        "tid": config["tenant"],
        "oid": next(iter(config["subjects"])),
        "azp": config["allowed_clients"][0],
        "ver": "2.0",
        "idtyp": "app",
        "roles": ["Detection.Viewer"],
        "iat": now,
        "nbf": now - 5,
        "exp": now + 300,
        **overrides,
    }
    return jwt.encode(
        claims,
        (ROOT / "work/local/development-signing-key.pem").read_bytes(),
        algorithm="RS256",
        headers={"kid": "local-development"},
    )
