import json
import logging
import time
from dataclasses import replace
from uuid import uuid4

import jwt
import pytest
from agenttrace_attribution import assess_authored_example
from agenttrace_contracts import DetectionDecision, utc_now
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

from agenttrace_foundation.api import create_app
from agenttrace_foundation.authorization import (
    AccessDenied,
    AuthorizationPolicy,
    EntraKeySet,
    EntraTokenValidator,
)

TENANT = "00000000-0000-4000-8000-000000000001"
AUDIENCE = "00000000-0000-4000-8000-000000000002"
CLIENT = "00000000-0000-4000-8000-000000000003"
SUBJECT = "00000000-0000-4000-8000-000000000004"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def policy():
    return AuthorizationPolicy(
        TENANT,
        AUDIENCE,
        frozenset({CLIENT}),
        {SUBJECT: frozenset({"approved"})},
        {"synthetic-example": "approved", "other-message": "excluded"},
    )


def encode(key, **overrides):
    now = int(time.time())
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": AUDIENCE,
        "tid": TENANT,
        "oid": SUBJECT,
        "azp": CLIENT,
        "ver": "2.0",
        "idtyp": "app",
        "roles": ["Detection.Viewer"],
        "iat": now,
        "nbf": now - 5,
        "exp": now + 300,
    }
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "unapproved"},
        {"aud": [AUDIENCE]},
        {"iss": "https://issuer.invalid"},
        {"tid": "wrong-tenant"},
        {"exp": 1},
        {"nbf": 4_000_000_000},
        {"iat": 4_000_000_000},
        {"exp": None},
        {"nbf": None},
        {"iat": None},
        {"oid": None},
        {"oid": "invalid"},
        {"azp": "unknown-client"},
        {"roles": []},
        {"roles": ["unassigned"]},
        {"roles": "Detection.Viewer"},
        {"roles": ["Detection.Administrator"]},
        {"idtyp": None},
        {"idtyp": "user", "scp": "unrelated"},
        {"ver": "1.0"},
        {"scp": "Detection.Read"},
    ],
)
def test_invalid_or_unauthorized_tokens_fail_closed(policy, signing_key, overrides):
    validator = EntraTokenValidator(policy, lambda _: signing_key.public_key())
    with pytest.raises(AccessDenied, match="invalid_access_token"):
        validator.validate(encode(signing_key, **overrides))


def test_wrong_signature_and_algorithm_are_rejected(policy, signing_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = EntraTokenValidator(policy, lambda _: signing_key.public_key())
    for token in [
        encode(other),
        jwt.encode(
            {"aud": AUDIENCE}, "fictional-test-only-key-with-32-characters", algorithm="HS256"
        ),
    ]:
        with pytest.raises(AccessDenied):
            validator.validate(token)


def test_signed_viewer_and_scoped_human_investigator_work(policy, signing_key):
    validator = EntraTokenValidator(policy, lambda _: signing_key.public_key())
    for overrides in [
        {},
        {"idtyp": "user", "roles": ["Detection.Investigator"], "scp": "Detection.Read"},
    ]:
        principal = validator.validate(encode(signing_key, **overrides))
        policy.authorize(principal, "synthetic-example")
        for ref in ["other-message", "missing"]:
            with pytest.raises(AccessDenied):
                policy.authorize(principal, ref)
        with pytest.raises(AccessDenied):
            policy.authorize(replace(principal, subject=str(uuid4())), "synthetic-example")


def test_public_health_and_deny_all_default_api():
    client = TestClient(create_app())
    assert client.get("/health/live").status_code == 200
    assert client.get("/v1/decisions/" + str(uuid4())).status_code == 401
    assert client.post("/v1/decisions/" + str(uuid4())).status_code == 405
    assert client.post("/send").status_code == 404


def test_real_http_authorization_before_data_and_message_entitlement(
    policy, signing_key, monkeypatch
):
    from pathlib import Path

    result = DetectionDecision(
        decision_id=uuid4(),
        message_ref="synthetic-example",
        observed_at=utc_now(),
        validation_basis="authored_contract_example",
        findings=assess_authored_example(
            Path(__file__).resolve().parents[2] / "examples/evidence-contract"
        ),
    )
    reads = []
    monkeypatch.setattr(
        "agenttrace_foundation.api.DecisionStore.get", lambda self, key: reads.append(key) or result
    )
    client = TestClient(
        create_app(
            policy=policy, validator=EntraTokenValidator(policy, lambda _: signing_key.public_key())
        )
    )
    url = "/v1/decisions/" + str(result.decision_id)
    assert client.get(url).status_code == 401 and not reads
    assert (
        client.get(
            url, headers={"Authorization": "Bearer " + encode(signing_key, exp=1)}
        ).status_code
        == 401
    )
    assert not reads
    headers = {"Authorization": "Bearer " + encode(signing_key)}
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    assert set(response.json()["findings"]) == {"agent_send_attribution", "content_assessment"}
    denied = replace(policy, messages={"synthetic-example": "excluded"})
    denied_client = TestClient(
        create_app(
            policy=denied, validator=EntraTokenValidator(denied, lambda _: signing_key.public_key())
        )
    )
    assert denied_client.get(url, headers=headers).status_code == 404


def test_jwks_unknown_key_refresh_is_bounded_and_local_keys_are_synthetic_only(
    policy, signing_key, tmp_path
):
    jwk = json.loads(RSAAlgorithm.to_jwk(signing_key.public_key()))
    jwk.update({"kid": "test-key", "use": "sig", "alg": "RS256"})
    path = tmp_path / "keys.json"
    path.write_text(json.dumps({"keys": [jwk]}))
    keys = EntraKeySet(replace(policy, local_jwks_file=path))
    assert keys("test-key").key_size == 2048
    for _ in range(3):
        with pytest.raises(AccessDenied):
            keys("untrusted")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"local_jwks_file": str(path)}))
    with pytest.raises(ValueError, match="forbidden_outside"):
        AuthorizationPolicy.load(settings, local_synthetic=False)


def test_security_audit_excludes_tokens_and_private_identifiers(policy, signing_key, caplog):
    validator = EntraTokenValidator(policy, lambda _: signing_key.public_key())
    token = encode(signing_key)
    with caplog.at_level(logging.INFO, logger="agenttrace.security"):
        policy.authorize(validator.validate(token), "synthetic-example")
    assert token not in caplog.text and SUBJECT not in caplog.text
    records = [json.loads(record.message) for record in caplog.records]
    assert all(set(record) == {"event", "outcome", "subject_ref"} for record in records)
