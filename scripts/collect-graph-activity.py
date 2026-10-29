"""Advance the configured Graph activity source; output aggregate health only."""

import argparse
import json
import time
from pathlib import Path

from agenttrace_foundation.database import StorageUnavailable
from agenttrace_ingestion.activity_runtime import load_activity
from agenttrace_ingestion.contracts import IngestionError

ROOT = Path(__file__).resolve().parents[1]


def collect_once():
    try:
        collector, _ = load_activity(ROOT)
        count = collector.collect()
        health = collector.store.health(collector.source_ref)
        result = {
            "graph_activity_records_added": count,
            "checkpoints": health["checkpoints"],
            "gaps": health["gaps"],
            "agent_attribution": "not_established_by_api_usage",
        }
        print(json.dumps(result))
        (ROOT / "work/private/graph-activity/collection-status.private.json").write_text(
            json.dumps(result, indent=2)
        )
        return 0
    except (IngestionError, StorageUnavailable) as error:
        print(json.dumps({"status": "unavailable", "reason_code": str(error)}))
        return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--interval", type=int, default=300, choices=range(60, 3601), metavar="SECONDS"
    )
    args = parser.parse_args()
    while True:
        result = collect_once()
        if not args.watch:
            return result
        for _ in range(args.interval // 60):
            time.sleep(60)
        if args.interval % 60:
            time.sleep(args.interval % 60)


if __name__ == "__main__":
    raise SystemExit(main())
