"""Enroll configured activity collection without resetting an existing checkpoint."""

import json
from pathlib import Path
from uuid import UUID

from agenttrace_ingestion.runtime import load

ROOT = Path(__file__).resolve().parents[1]


def main():
    path = ROOT / "work/private/graph-activity/logging-settings.private.json"
    settings = json.loads(path.read_text())
    if not settings.get("workspaceCustomerId") or not settings.get("enabled_at"):
        raise RuntimeError("completed_graph_logging_configuration_required")
    _, enrollment, operator, _, _ = load(
        ROOT / "work/private/mail-ingestion/runtime.private.json", operator=True
    )
    refs = json.loads((ROOT / "work/private/mail-ingestion/audit-sources.private.json").read_text())
    source = UUID(refs["graph_activity"])
    operator.enroll(
        enrollment.model_copy(update={"source_ref": source}),
        kind="graph_activity",
        alias="graph-activity",
    )
    with operator.database.connect() as connection:
        connection.execute(
            "UPDATE ingest_checkpoints SET coverage='retired',reason_code='pre_enable_partition_retired',lease=NULL,lease_until=NULL WHERE source_ref=%s AND partition_ref=%s",
            (source, operator.cipher.reference(str(source), "graph_activity")),
        )
    if not settings.get("source_initialized"):
        with operator.database.connect() as connection:
            connection.execute(
                "UPDATE ingest_checkpoints SET coverage='pending',reason_code='graph_activity_initial_sync_required',next_attempt=now(),lease=NULL,lease_until=NULL WHERE source_ref=%s",
                (source,),
            )
            connection.execute(
                "UPDATE ingest_gaps SET disposition='unrecoverable',ended_at=now() WHERE source_ref=%s AND reason_code='graph_activity_destination_not_configured' AND disposition='open'",
                (source,),
            )
    settings.update({"enabled": True, "source_initialized": True})
    path.write_text(json.dumps(settings, indent=2))
    print(
        json.dumps(
            {
                "graph_activity_source_enrolled": True,
                "historical_pre_enable_gap": "unrecoverable_unknown_count",
                "existing_checkpoint_preserved": True,
            }
        )
    )


if __name__ == "__main__":
    main()
