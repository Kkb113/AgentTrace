"""Run every shared foundation gate and record reproducible, sanitized results."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    reports = ROOT / "work/reports"
    reports.mkdir(parents=True, exist_ok=True)
    gates = {}
    for name in ["quality", "security", "infrastructure", "integration", "guard-controls"]:
        start = time.monotonic()
        result = subprocess.run(
            [sys.executable, "scripts/ci-checks.py", name], cwd=ROOT, shell=False, check=False
        )
        gates[name] = {
            "exit_code": result.returncode,
            "elapsed_seconds": round(time.monotonic() - start, 3),
        }
        if result.returncode:
            break
    counts = {}
    for name in ["unit", "integration"]:
        source = reports / (name + ".xml")
        if source.is_file():
            suite = ET.parse(source).getroot().find("testsuite")
            if suite is not None:
                counts[name] = {
                    key: int(suite.attrib[key])
                    for key in ["tests", "errors", "failures", "skipped"]
                }
    exits = json.loads((ROOT / "config/foundation-exits.json").read_text())
    passed = len(gates) == 5 and all(value["exit_code"] == 0 for value in gates.values())
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "gates": gates,
        "junit_counts": counts,
        "all_local_gates_pass": passed,
        "recorded_exit_criteria_met": sum(entry["met"] for entry in exits["exits"]),
        "recorded_exit_criteria_total": len(exits["exits"]),
        "resources_provisioned_in_azure": 0,
        "qualification_claim": "Foundation validation only; authored fixtures do not establish detector accuracy or Azure Queue parity.",
    }
    (reports / "foundation-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
