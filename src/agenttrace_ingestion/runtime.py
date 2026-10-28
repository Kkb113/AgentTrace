"""Private synthetic runtime wiring; no credentials or source records are printed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agenttrace_foundation.database import Database
from agenttrace_foundation.settings import Settings
from agenttrace_foundation.workload_identity import CertificateTokenProvider

from .contracts import Enrollment, IngestionError
from .mailbox import MailboxClient
from .pipeline import MailboxPipeline
from .protection import EvidenceCipher
from .store import IngestionStore
from .transport import MicrosoftTransport


def load(
    config_file: Path, *, operator: bool = False
) -> tuple[dict[str, Any], Enrollment, IngestionStore, MailboxPipeline, CertificateTokenProvider]:
    root = Path.cwd().resolve()
    if not config_file.resolve().is_relative_to(root / "work/private"):
        raise IngestionError("private_ingestion_configuration_required")
    config = json.loads(config_file.read_text(encoding="utf-8"))
    enrollment = Enrollment.model_validate(config["enrollment"])
    secret_root = root / "work/local"
    key_path = Path(config["evidence_key_file"]).resolve()
    public_path = Path(config["content_public_key_file"]).resolve()
    if not key_path.is_relative_to(root / "work/private") or not public_path.is_relative_to(
        root / "work/private"
    ):
        raise IngestionError("private_ingestion_key_path_required")
    settings = Settings(
        "127.0.0.1",
        55432,
        secret_root / ("postgres-password" if operator else "roles/collector-password"),
        "agenttrace" if operator else "agenttrace_collector",
    )
    cipher = EvidenceCipher(key_path.read_bytes())
    store = IngestionStore(Database(settings), cipher)
    identity = config["mail_identity"]
    provider = CertificateTokenProvider(
        str(enrollment.tenant_id),
        str(enrollment.collector_client_id),
        identity["thumbprint"],
        root / "scripts/manage-workload-certificate.ps1",
    )
    public = serialization.load_pem_public_key(public_path.read_bytes())
    if not isinstance(public, rsa.RSAPublicKey):
        raise IngestionError("rsa_content_public_key_required")
    mailbox = MailboxClient(
        enrollment,
        MicrosoftTransport(
            lambda *, force_refresh=False: provider.token(
                "https://graph.microsoft.com", force_refresh=force_refresh
            )
        ),
    )
    return config, enrollment, store, MailboxPipeline(store, mailbox, public), provider
