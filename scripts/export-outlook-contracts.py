"""Generate/check standalone Outlook contracts without modifying legacy contracts."""

import argparse
import json
from pathlib import Path

from agenttrace_outlook.config import RuntimeConfig
from agenttrace_outlook.contracts import Decision, FixtureBatch, Observation
from agenttrace_outlook.sender_rules import RuleAssessment

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, model in (
        ("outlook-runtime", RuntimeConfig),
        ("outlook-observation", Observation),
        ("outlook-decision", Decision),
        ("outlook-fixtures", FixtureBatch),
        ("sender-rule-assessment", RuleAssessment),
    ):
        path = ROOT / "packages/contracts/schemas" / (name + ".schema.json")
        expected = json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                print("Generated Outlook contract is stale: " + name)
                return 1
        else:
            path.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
