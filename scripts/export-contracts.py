"""Generate or check the frozen JSON Schema consumed by future UI clients."""

import argparse
import json
from pathlib import Path

from agenttrace_contracts import DetectionDecision, DetectionJob

from agenttrace_ledger.contracts import CorrelationView, MessageObservation, SignedEvidence

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, model in [
        ("detection-decision", DetectionDecision),
        ("detection-job", DetectionJob),
        ("signed-evidence", SignedEvidence),
        ("message-observation", MessageObservation),
        ("correlation-view", CorrelationView),
    ]:
        path = ROOT / "packages/contracts/schemas" / (name + ".schema.json")
        expected = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.is_file() or path.read_text() != expected:
                print("Generated contract is stale: " + name)
                return 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
