import base64
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agenttrace_foundation.settings import Settings
from agenttrace_ledger.canonical import LedgerError, message_material
from agenttrace_ledger.contracts import Region
from agenttrace_ledger.runtime import load_ledger
from tests.ingestion_support import TENANT
from tests.ledger_support import observation


def test_runtime_configuration_requires_explicit_valid_keys(tmp_path):
    settings = Settings("127.0.0.1", 55432, Path("unused-test-password"), "agenttrace_ledger")
    path = tmp_path / "ledger-keys.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "encryption_key": base64.b64encode(bytes(32)).decode(),
                "tenant_fingerprint_keys": {
                    str(TENANT): base64.b64encode(bytes([9]) * 32).decode()
                },
            }
        )
    )
    ledger = load_ledger(settings, path)
    assert ledger.database.settings.database_user == "agenttrace_ledger"
    data = json.loads(path.read_text())
    data["tenant_fingerprint_keys"][str(TENANT)] = "invalid"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_ledger(settings, path)


def test_absent_body_or_recipients_cannot_acquire_a_complete_payload_fingerprint():
    missing = observation(body="", content_available=False, recipients_complete=False)
    material = message_material(missing, bytes(32))
    assert material["body_digest"] is None and material["payload_digest"] is None
    assert material["regions"] == []
    with pytest.raises(ValidationError):
        observation(content_available=False)


@pytest.mark.parametrize(
    "regions",
    [
        (Region(start=0, end=5, role="authored"), Region(start=3, end=8, role="authored")),
        (Region(start=0, end=10000, role="authored"),),
    ],
)
def test_invalid_region_offsets_never_establish_content_lineage(regions):
    with pytest.raises(LedgerError, match="canonical_region"):
        message_material(observation(regions=regions), bytes(32))


def test_snapshot_requires_explicit_authorization_and_a_bounded_reference():
    from uuid import uuid4

    with pytest.raises(ValidationError):
        observation(snapshot_ref=uuid4())
