"""Bind executed tests and live evidence to the reviewed Graph activity source files."""

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    foundation = json.loads((ROOT / "work/reports/foundation-validation.json").read_text())
    live = json.loads((ROOT / "docs/evidence/graph-activity-live-validation.json").read_text())
    executed = {}
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
    required = [
        "test_transform_is_narrow_and_drops_sensitive_fields_before_storage",
        "test_unbounded_or_inconsistent_source_scopes_are_rejected",
        "test_supported_send_api_calls_are_only_send_observations",
        "test_drafts_edits_reads_failures_and_other_resources_are_not_send_events",
        "test_uri_minimization_removes_queries_and_fragments_without_changing_object_path",
        "test_untrusted_activity_uris_are_rejected",
        "test_delayed_arrivals_overlap_deduplicate_and_remove_uri_queries",
        "test_empty_initial_delivery_is_pending_and_not_negative_agent_evidence",
        "test_failed_windows_never_advance_checkpoints_or_partially_commit",
        "test_only_noncollector_successful_send_api_operations_are_correlation_candidates",
    ]
    paths = [
        "src/agenttrace_ingestion/activity_policy.py",
        "src/agenttrace_ingestion/activity_runtime.py",
        "src/agenttrace_ingestion/graph_activity.py",
        "src/agenttrace_foundation/workload_identity.py",
        "infra/bicep/graph-activity-logging.bicep",
        "scripts/collect-audit-evidence.py",
        "scripts/collect-graph-activity.py",
        "scripts/configure-graph-activity.py",
        "scripts/inspect-graph-activity.py",
        "scripts/prepare-graph-activity.py",
        "scripts/probe-graph-activity.py",
        "scripts/verify-graph-activity.py",
        "scripts/validate-infrastructure.py",
        "tests/unit/test_graph_activity_policy.py",
        "tests/integration/test_graph_activity_collection.py",
    ]
    result = {
        "executed_at": datetime.now(UTC).isoformat(),
        "all_five_local_gates_pass": foundation["all_local_gates_pass"],
        "primary_test_counts": counts,
        "required_regressions": {name: executed.get(name, False) for name in required},
        "live_validation_passed": live["all_passed"],
        "files": [
            {
                "path": name,
                "sha256": hashlib.sha256(
                    (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
                ).hexdigest(),
            }
            for name in paths
        ],
        "file_hash_normalization": "Git LF text bytes",
        "scope": "Graph API-request evidence only; no API-only AI verdict, mailbox write or content scoring",
    }
    result["all_passed"] = (
        result["all_five_local_gates_pass"]
        and result["live_validation_passed"]
        and all(result["required_regressions"].values())
    )
    (ROOT / "docs/evidence/graph-activity-validation.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
