from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agenttrace_foundation.authorization import EntraTokenValidator
from agenttrace_ledger.api import create_app
from agenttrace_ledger.store import EvidenceLedger
from tests.development_identity import development_policy, development_token
from tests.ingestion_support import CLIENT, MAILBOX, TENANT, cipher
from tests.ledger_support import enrolled, observation, send_fact, signed

pytestmark = pytest.mark.integration


@pytest.fixture
def api_case(database):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    issuer, key, private = enrolled(ledger, message)
    ref = ledger.observe(message)
    policy = replace(
        development_policy(),
        subjects={str(CLIENT): frozenset({str(MAILBOX)})},
        messages={str(ref): str(MAILBOX)},
    )
    app = create_app(ledger, policy=policy, validator=EntraTokenValidator(policy))
    return ledger, message, ref, issuer, key, private, TestClient(app), policy


def authorization(**changes):
    claims = {"oid": str(CLIENT), "roles": ["Detection.Viewer"], **changes}
    return {"Authorization": "Bearer " + development_token(**claims)}


def test_signed_submission_traceable_inputs_and_restart_history_end_to_end(api_case):
    ledger, message, ref, issuer, key, private, client, policy = api_case
    envelope = signed(message, ref, issuer, key, private, send_fact(message))
    posted = client.post(
        "/v1/evidence/receipts", headers=authorization(), content=envelope.model_dump_json()
    )
    assert posted.status_code == 200
    endpoint = f"/v1/evidence/messages/{ref}/versions/{message.version_ref}"
    result = client.get(endpoint, headers=authorization())
    assert result.status_code == 200
    assert result.json()["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
    assert "flagged" not in result.text
    inputs = client.post(
        endpoint + "/inputs",
        headers=authorization(idtyp="user", scp="Detection.Read", roles=["Detection.Investigator"]),
    )
    assert inputs.status_code == 200
    restarted = TestClient(
        create_app(
            EvidenceLedger(ledger.database, cipher(), {TENANT: bytes([9]) * 32}),
            policy=policy,
            validator=EntraTokenValidator(policy),
        )
    )
    history = restarted.get(f"/v1/evidence/messages/{ref}/history", headers=authorization())
    assert history.status_code == 200
    assert history.json()["history"][0]["input_ref"] == inputs.json()["input_ref"]
    assert history.json()["history"][0]["historical_only"] is True
    assert message.body not in result.text + history.text
    assert message.immutable_id not in result.text + history.text


@pytest.mark.parametrize(
    "claims,expected",
    [
        ({"tid": str(uuid4())}, 401),
        ({"aud": str(uuid4())}, 401),
        ({"azp": str(uuid4())}, 401),
        ({"oid": str(uuid4())}, 404),
    ],
)
def test_api_rejects_wrong_tenant_audience_client_and_subject(api_case, claims, expected):
    ledger, message, ref, issuer, key, private, client, policy = api_case
    defaults = {"oid": str(CLIENT), "roles": ["Detection.Viewer"], **claims}
    headers = {"Authorization": "Bearer " + development_token(**defaults)}
    response = client.get(
        f"/v1/evidence/messages/{ref}/versions/{message.version_ref}", headers=headers
    )
    assert response.status_code == expected


def test_unknown_issuer_forged_signature_and_delegated_publisher_are_denied(api_case):
    ledger, message, ref, issuer, key, private, client, policy = api_case
    envelope = signed(message, ref, issuer, key, private, send_fact(message))
    forged = envelope.model_dump(mode="json")
    forged["record"]["fact"]["actor"] = "human"
    unknown = signed(message, ref, uuid4(), key, private, send_fact(message))
    assert (
        client.post(
            "/v1/evidence/receipts", headers=authorization(), content=unknown.model_dump_json()
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/evidence/messages/{ref}/versions/{message.version_ref}/inputs",
            headers=authorization(),
        ).status_code
        == 403
    )
    assert (
        client.post("/v1/evidence/receipts", headers=authorization(), json=forged).status_code
        == 403
    )
    delegated = authorization(idtyp="user", scp="Detection.Read")
    assert (
        client.post(
            "/v1/evidence/receipts", headers=delegated, content=envelope.model_dump_json()
        ).status_code
        == 403
    )
    assert (
        client.post("/v1/evidence/receipts", content=envelope.model_dump_json()).status_code == 401
    )
    assert client.post(
        "/v1/evidence/receipts", headers=authorization(), content=b'{"bogus":"private-text-canary"}'
    ).json() == {"detail": "invalid_signed_evidence"}


@pytest.mark.parametrize(
    "body,expected", [(b'{"a":1,"a":2}', 422), (b'{"a":NaN}', 422), (b"x" * 65537, 413)]
)
def test_request_limits_and_json_ambiguity_never_echo_input(api_case, body, expected):
    *_, client, policy = api_case
    response = client.post("/v1/evidence/receipts", headers=authorization(), content=body)
    assert response.status_code == expected
    assert "input" not in response.json()


@pytest.mark.parametrize("credential_file_failure", [False, True])
def test_storage_failure_has_a_safe_503_and_no_successful_ack(
    api_case, monkeypatch, credential_file_failure
):
    from agenttrace_foundation.database import StorageUnavailable

    ledger, message, ref, issuer, key, private, client, policy = api_case

    def fail(*args, **kwargs):
        if credential_file_failure:
            raise OSError("private-path-canary")
        raise StorageUnavailable("local_database_operation_failed")

    monkeypatch.setattr(ledger, "submit", fail)
    response = client.post(
        "/v1/evidence/receipts",
        headers=authorization(),
        content=signed(message, ref, issuer, key, private, send_fact(message)).model_dump_json(),
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "evidence_store_unavailable"}


def test_readiness_is_unavailable_without_authentication_or_storage(api_case, monkeypatch):
    from agenttrace_foundation.database import StorageUnavailable

    ledger, message, ref, issuer, key, private, client, policy = api_case
    assert client.get("/health/ready").status_code == 200
    assert TestClient(create_app(ledger)).get("/health/ready").status_code == 503

    def fail():
        raise StorageUnavailable("local_database_operation_failed")

    monkeypatch.setattr(ledger.database, "connect", fail)
    assert client.get("/health/ready").status_code == 503


def test_frozen_openapi_has_resolvable_evidence_definitions(api_case):
    *_, client, policy = api_case
    document = client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    assert (
        schemas["SignedEvidence"]["properties"]["record"]["$ref"]
        == "#/components/schemas/EvidenceRecord"
    )
    assert (
        schemas["EvidenceRecord"]["properties"]["fact"]["discriminator"]["propertyName"] == "kind"
    )
    assert "Generation" in schemas and "CorrelationView" in schemas
