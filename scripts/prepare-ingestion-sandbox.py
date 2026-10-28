"""Create private local keys/configuration for the existing authorized test mailbox."""

import json
import secrets
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "work/private/mail-ingestion"
    baseline = ROOT / "work/private/secure-access"
    settings = json.loads(
        (baseline / "sandbox-settings.private.json").read_text(encoding="utf-8-sig")
    )
    identities = json.loads((baseline / "workload-identities.private.json").read_text())
    folders = json.loads((directory / "pilot-folders.private.json").read_text())
    if not folders or any(f["displayName"] != "AgentTrace Synthetic" for f in folders):
        raise RuntimeError("operator_prepared_synthetic_folder_required")
    path = directory / "runtime.private.json"
    if path.exists():
        print(json.dumps({"configuration": "existing_private_configuration_preserved"}))
        return
    transport = json.loads((directory / "transport-settings.private.json").read_text())
    evidence_key = directory / "evidence-encryption.key"
    evidence_key.write_bytes(secrets.token_bytes(32))
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    (directory / "content-input-private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public = directory / "content-input-public.pem"
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    enrollment = {
        "source_ref": str(uuid4()),
        "tenant_id": settings["tenant"],
        "mailbox_id": settings["mailbox_id"],
        "collector_client_id": identities["mail-collector"]["application"]["appId"],
        "folder_ids": [f["id"] for f in folders],
        "client_state": secrets.token_urlsafe(40),
        "raw_snapshots_allowed": False,
    }
    config = {
        "enrollment": enrollment,
        "evidence_key_file": str(evidence_key),
        "content_public_key_file": str(public),
        "mail_identity": {"thumbprint": identities["mail-collector"]["certificate"]["thumbprint"]},
        "notification_storage_account": transport["storageAccountName"],
        "notification_url": "EventGrid:?azuresubscriptionid="
        + settings["subscription"]
        + "&resourcegroup=kb-agentdemo&partnertopic="
        + transport["partner_topic_name"]
        + "&location=eastus",
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "configuration": "prepared",
                "folder_count": len(folders),
                "retained_raw_snapshots": False,
            }
        )
    )


if __name__ == "__main__":
    main()
