"""Run local end-to-end/security checks and produce a sanitized evidence report."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import unittest
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from agenttrace_feasibility.attribution import assess_bundle  # noqa: E402
from agenttrace_feasibility.validation import timestamp  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work/reports/local-validation.json")
    arguments = parser.parse_args()
    output = arguments.output.resolve()
    if not output.is_relative_to(ROOT / "work/reports"):
        parser.error("Report output must stay in the ignored work/reports directory")
    baseline = json.loads((ROOT / "config/poc-baseline.json").read_text())
    exits = json.loads((ROOT / "config/feasibility-exits.json").read_text())
    live = json.loads((ROOT / "docs/evidence/live-audit-validation.json").read_text())
    live_cases = live["cases"]
    recorded_live_valid = (
        len(live_cases) == 3
        and live_cases[0]["ground_truth"]["agent_sent"] is True
        and live_cases[0]["findings"]["agent_send_attribution"]["flagged"] is True
        and all(
            case["ground_truth"]["agent_sent"] is False
            and case["findings"]["agent_send_attribution"]["flagged"] is not True
            for case in live_cases[1:]
        )
        and live["copied_control_text_matches_supplied_generation"] is True
    )
    required_outputs = ["agent_send_attribution", "content_assessment"]
    baseline_valid = (
        baseline["findings"] == required_outputs
        and baseline["primary_finding"] == required_outputs[0]
        and baseline["synthetic_data_only"] is True
        and baseline["content_scores_can_influence_agent_finding"] is False
        and baseline["mailbox_write_or_send_permissions_allowed"] is False
        and baseline["resource_group"] == "kb-agentdemo"
    )
    references_valid = len(exits["exits"]) == 9 and all(
        (ROOT / item).is_file() for entry in exits["exits"] for item in entry["evidence"]
    )
    bad_names = [
        str(path.relative_to(ROOT))
        for folder in ["src", "tests", "scripts", "docs", "config", "examples"]
        for path in (ROOT / folder).rglob("*")
        if path.is_file() and re.search(r"phase[-_ ]?\d", path.name, re.IGNORECASE)
    ]
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)
    print(stream.getvalue(), file=sys.stderr)
    example = assess_bundle(
        ROOT / "examples/evidence-contract",
        ROOT / "examples/evidence-contract/trust-profile.json",
        timestamp("2026-10-28T10:10:00Z"),
    )
    example_valid = example["decisions"][0]["findings"][required_outputs[0]]["flagged"] is True
    report = {
        "executed_at": datetime.now(UTC).isoformat(),
        "python_version": sys.version.split()[0],
        "cryptography_version": version("cryptography"),
        "msal_version": version("msal"),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "baseline_invariants_pass": baseline_valid,
        "evidence_references_exist": references_valid,
        "descriptive_filename_check_pass": not bad_names,
        "public_contract_cli_input_pass": example_valid,
        "recorded_live_exercise_consistent": recorded_live_valid,
        "local_validation_pass": result.wasSuccessful()
        and baseline_valid
        and references_valid
        and not bad_names
        and example_valid
        and recorded_live_valid,
        "exit_criteria_met": sum(entry["met"] for entry in exits["exits"]),
        "exit_criteria_total": 9,
        "initial_stage_complete": all(entry["met"] for entry in exits["exits"]),
        "live_source_link": "authenticated_exchange_send_enrolled_connector_scoped_unique_sent_item_join",
        "live_validation_basis": "Reviewed earlier live capture; this local command does not reauthenticate or rerun Microsoft 365 queries.",
        "qualification_claim": "Local synthetic contract tests are not independent tenant accuracy evidence; G1/G2 and release C criteria remain unmeasured.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return 0 if report["local_validation_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
