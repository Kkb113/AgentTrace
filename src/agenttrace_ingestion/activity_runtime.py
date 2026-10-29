"""Connect the approved table reader to a private, source-enrolled activity stream."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from agenttrace_foundation.database import Database
from agenttrace_foundation.settings import Settings
from agenttrace_foundation.workload_identity import CertificateTokenProvider

from .contracts import Enrollment, IngestionError
from .graph_activity import GraphActivityCollector
from .protection import EvidenceCipher
from .store import IngestionStore
from .transport import MicrosoftTransport


def enroll_activity_source(store: IngestionStore, enrollment: Enrollment, source_ref: UUID) -> None:
    """Retire pre-enable state without resetting any active checkpoint or lease."""
    store.enroll(
        enrollment.model_copy(update={"source_ref": source_ref}),
        kind="graph_activity",
        alias="graph-activity",
    )
    active = store.cipher.reference(str(source_ref), "graph-activity")
    retired = store.cipher.reference(str(source_ref), "graph_activity")
    with store.database.connect() as connection:
        connection.execute(
            "INSERT INTO ingest_checkpoints(source_ref,partition_ref,reason_code) VALUES (%s,%s,'graph_activity_initial_sync_required') ON CONFLICT DO NOTHING",
            (source_ref, active),
        )
        connection.execute(
            "UPDATE ingest_checkpoints SET coverage='retired',reason_code='pre_enable_partition_retired',generation=generation+1,lease=NULL,lease_until=NULL WHERE source_ref=%s AND partition_ref=%s AND coverage<>'retired'",
            (source_ref, retired),
        )
        connection.execute(
            "UPDATE ingest_gaps SET disposition='unrecoverable',ended_at=now() WHERE source_ref=%s AND reason_code='graph_activity_destination_not_configured' AND disposition='open'",
            (source_ref,),
        )


def load_activity(root: Path) -> tuple[GraphActivityCollector, dict[str, object]]:
    directory = root / "work/private/graph-activity"
    settings = json.loads((directory / "logging-settings.private.json").read_text())
    if not settings.get("enabled"):
        raise IngestionError("graph_activity_source_not_enabled")
    runtime = json.loads((root / "work/private/mail-ingestion/runtime.private.json").read_text())
    refs = json.loads((root / "work/private/mail-ingestion/audit-sources.private.json").read_text())
    database = Database(
        Settings(
            "127.0.0.1", 55432, root / "work/local/roles/collector-password", "agenttrace_collector"
        )
    )
    evidence_path = Path(runtime["evidence_key_file"]).resolve()
    if not evidence_path.is_relative_to(root / "work/private"):
        raise IngestionError("private_ingestion_key_path_required")
    store = IngestionStore(database, EvidenceCipher(evidence_path.read_bytes()))
    provider = CertificateTokenProvider(
        settings["tenant_id"],
        settings["reader_client_id"],
        settings["reader_thumbprint"],
        root / "scripts/manage-workload-certificate.ps1",
    )
    transport = MicrosoftTransport(
        lambda *, force_refresh=False: provider.token(
            "https://api.loganalytics.io", force_refresh=force_refresh
        ),
        host="api.loganalytics.azure.com",
    )
    collector = GraphActivityCollector(
        store,
        transport,
        UUID(refs["graph_activity"]),
        UUID(settings["workspaceCustomerId"]),
        tenant=UUID(settings["tenant_id"]),
        clients={UUID(v) for v in settings["clients"]},
        collector_clients={UUID(v) for v in settings["collector_clients"]},
        pilot_user=UUID(settings["pilot_user_id"]),
    )
    return collector, settings
