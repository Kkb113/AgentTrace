"""Verify all ingestion exits from executed CI gates and actual live-source evidence."""

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-current-gates", action="store_true")
    args = parser.parse_args()
    if not args.reuse_current_gates:
        result = subprocess.run([sys.executable, "scripts/verify-foundation.py"], cwd=ROOT)
        if result.returncode:
            return result.returncode
    foundation = json.loads((ROOT / "work/reports/foundation-validation.json").read_text())
    checks = {}
    counts = {}
    for label in ["unit", "integration"]:
        suites = ET.parse(ROOT / "work/reports" / (label + ".xml")).getroot()
        cases = suites.findall(".//testcase")
        counts[label] = {
            "tests": len(cases),
            "failed": sum(
                case.find("failure") is not None or case.find("error") is not None for case in cases
            ),
            "skipped": sum(case.find("skipped") is not None for case in cases),
        }
        for case in cases:
            name = case.attrib["name"].split("[")[0]
            passed = (
                case.find("failure") is None
                and case.find("error") is None
                and case.find("skipped") is None
            )
            checks[name] = checks.get(name, True) and passed
    exits = json.loads((ROOT / "config/mail-ingestion-exits.json").read_text())["exits"]
    for entry in exits:
        entry["met"] = all(checks.get(name, False) for name in entry["required_tests"])
    live = json.loads((ROOT / "docs/evidence/mail-ingestion-live-validation.json").read_text())
    files = [
        p
        for directory in [
            "src/agenttrace_ingestion",
            "packages/text-normalization/src",
            "tests/integration",
            "tests/unit",
        ]
        for p in (ROOT / directory).rglob("*.py")
    ]
    files += [
        ROOT / name
        for name in [
            "src/agenttrace_foundation/migrations/ingestion.sql",
            "src/agenttrace_foundation/database_access.py",
            "pyproject.toml",
            "uv.lock",
            "infra/bicep/notification-transport.bicep",
            "config/language-artifacts.json",
        ]
    ]
    manifest = [
        {
            "path": str(p.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        }
        for p in sorted(files)
    ]
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "all_five_gates_pass": foundation["all_local_gates_pass"],
        "test_counts": counts,
        "exits": exits,
        "live_validation_passed": live["all_passed"],
        "files": manifest,
        "file_hash_normalization": "Git LF text bytes",
        "accuracy_qualification": "Not claimed; no statistical authorship model or production agent detector installed in this milestone.",
    }
    report["all_exit_criteria_met"] = (
        all(e["met"] for e in exits)
        and report["all_five_gates_pass"]
        and report["live_validation_passed"]
    )
    (ROOT / "docs/evidence/mail-ingestion-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "files"}, indent=2))
    return 0 if report["all_exit_criteria_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
