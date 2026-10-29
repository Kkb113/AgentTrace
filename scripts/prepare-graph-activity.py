"""Enroll configured activity collection without resetting an existing checkpoint."""

import json
from pathlib import Path
from uuid import UUID

from agenttrace_ingestion.activity_runtime import enroll_activity_source
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
    enroll_activity_source(operator, enrollment, source)
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
