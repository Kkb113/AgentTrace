"""Bind Phase 4 exits to executed tests, published contracts and reviewed source hashes."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    foundation = json.loads((ROOT / "work/reports/foundation-validation.json").read_text())
    review = json.loads((ROOT / "config/evidence-ledger-exits.json").read_text())
    executed: dict[str, bool] = {}
    counts = {}
    for group in ["unit", "integration"]:
        cases = ET.parse(ROOT / "work/reports" / (group + ".xml")).getroot().findall(".//testcase")
        counts[group] = len(cases)
        for case in cases:
            name = case.attrib["name"].split("[")[0]
            passed = not any(
                case.find(kind) is not None for kind in ["failure", "error", "skipped"]
            )
            executed[name] = executed.get(name, True) and passed
    exits = [
        {
            "id": entry["id"],
            "met": all(executed.get(name, False) for name in entry["required_tests"]),
            "required_tests": {name: executed.get(name, False) for name in entry["required_tests"]},
        }
        for entry in review["exits"]
    ]
    paths = [
        *sorted((ROOT / "src/agenttrace_ledger").glob("*.py")),
        ROOT / "src/agenttrace_foundation/migrations/ledger.sql",
        ROOT / "src/agenttrace_foundation/database.py",
        ROOT / "src/agenttrace_foundation/database_access.py",
        ROOT / "src/agenttrace_foundation/settings.py",
        ROOT / "compose.yaml",
        ROOT / ".github/workflows/validation.yml",
        ROOT / "ci/azure-pipelines.yml",
        ROOT / "scripts/prepare-local-security.py",
        ROOT / "tests/unit/test_validation_configuration.py",
        ROOT / "pyproject.toml",
        ROOT / "scripts/check-boundaries.py",
        ROOT / "scripts/export-contracts.py",
        ROOT / "config/evidence-ledger-exits.json",
        ROOT / "docs/evidence-schema.md",
        ROOT / "docs/correlation-rules.md",
        ROOT / "docs/runbooks/evidence-ledger.md",
        *sorted((ROOT / "tests/integration").glob("test_*ledger*.py")),
        ROOT / "tests/integration/test_evidence_api.py",
        ROOT / "tests/ledger_support.py",
        ROOT / "tests/unit/test_evidence_canonicalization.py",
        ROOT / "tests/unit/test_ledger_runtime.py",
        *[
            ROOT / "packages/contracts/schemas" / (name + ".schema.json")
            for name in ["signed-evidence", "message-observation", "correlation-view"]
        ],
    ]
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    result = {
        "executed_at": datetime.now(UTC).isoformat(),
        "all_five_local_gates_pass": foundation["all_local_gates_pass"],
        "primary_test_counts": counts,
        "additional_unit_subtests": foundation["junit_counts"]["unit"]["tests"] - counts["unit"],
        "exits": exits,
        "missing_required_artifacts": missing,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            }
            for path in paths
            if path.is_file()
        ],
        "hash_normalization": "Git LF text bytes",
        "test_environment": "Local PostgreSQL 17 and real loopback HTTP with fictional Entra tokens and independently signed synthetic evidence",
        "new_azure_resources": 0,
        "new_microsoft_365_permissions": 0,
        "email_mutations": 0,
        "graph_activity_source_qualified_by_this_validation": False,
        "production_accuracy_or_WORM_qualification_claimed": False,
    }
    result["all_exit_criteria_met"] = (
        foundation["all_local_gates_pass"] and not missing and all(entry["met"] for entry in exits)
    )
    (ROOT / "docs/evidence/evidence-ledger-validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
    return 0 if result["all_exit_criteria_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
