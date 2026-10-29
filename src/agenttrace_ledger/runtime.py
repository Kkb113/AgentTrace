"""Explicit local runtime configuration. No auto-enrollment, key downloads or cloud writes."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from uuid import UUID

import uvicorn

from agenttrace_foundation.authorization import (
    AuthorizationPolicy,
    EntraTokenValidator,
    configure_security_logging,
)
from agenttrace_foundation.database import Database
from agenttrace_foundation.settings import Settings
from agenttrace_ingestion.protection import EvidenceCipher

from .api import create_app
from .store import EvidenceLedger


def load_ledger(settings: Settings, key_file: Path) -> EvidenceLedger:
    data = json.loads(key_file.read_text(encoding="utf-8"))
    if (
        set(data) != {"schema_version", "encryption_key", "tenant_fingerprint_keys"}
        or data["schema_version"] != "1.0"
    ):
        raise ValueError("invalid_ledger_key_configuration")
    cipher = EvidenceCipher(base64.b64decode(data["encryption_key"], validate=True))
    tenants = {
        UUID(tenant): base64.b64decode(value, validate=True)
        for tenant, value in data["tenant_fingerprint_keys"].items()
    }
    if not tenants or any(len(key) != 32 for key in tenants.values()):
        raise ValueError("invalid_ledger_tenant_keys")
    return EvidenceLedger(Database(settings), cipher, tenants)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args()
    configure_security_logging()
    try:
        settings = Settings.from_environment()
        if settings.database_user != "agenttrace_ledger":
            raise ValueError("separate_ledger_runtime_identity_required")
        ledger = load_ledger(settings, args.keys)
        policy = AuthorizationPolicy.load(
            args.authorization,
            local_synthetic=os.environ.get("AGENTTRACE_ENVIRONMENT", "local_synthetic")
            == "local_synthetic",
        )
        uvicorn.run(
            create_app(ledger, policy=policy, validator=EntraTokenValidator(policy)),
            host="127.0.0.1",
            port=8082,
            access_log=False,
        )
        return 0
    except (ValueError, OSError):
        print(json.dumps({"status": "failed", "reason": "ledger_runtime_configuration_invalid"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
