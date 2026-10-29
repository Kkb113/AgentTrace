"""One controlled refresh of the dedicated Graph export after the destination passes."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_ingestion.activity_diagnostics import graph_route_enabled, route_toggle_payload
from agenttrace_ingestion.activity_runtime import load_activity
from agenttrace_ingestion.runtime import load

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--record-recovery",
        action="store_true",
        help="Record restoration from saved API receipts without another toggle",
    )
    args = parser.parse_args()
    directory = ROOT / "work/private/graph-activity"
    config = json.loads(
        (ROOT / "work/private/secure-access/sandbox-settings.private.json").read_text(
            encoding="utf-8-sig"
        )
    )
    collector, settings = load_activity(ROOT)

    def az(label, commands, *, allow_missing=False):
        response = subprocess.run(
            [
                *azure_cli_prefix(),
                *commands,
                "--subscription",
                config["subscription"],
                "--only-show-errors",
                "-o",
                "json",
            ],
            capture_output=True,
            timeout=90,
        )
        (directory / ("refresh-" + label + ".private.json")).write_bytes(response.stdout)
        if response.returncode:
            (directory / ("refresh-" + label + ".error.private.txt")).write_bytes(response.stderr)
            if allow_missing and b"ResourceNotFound" in response.stderr:
                return {"resource_absent": True}
            raise RuntimeError("route_refresh_command_failed_see_private_capture")
        return json.loads(response.stdout)

    if settings["diagnostic_setting_name"] != "AgentTraceGraphActivity":
        raise RuntimeError("dedicated_agenttrace_setting_required")
    url = "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings/AgentTraceGraphActivity?api-version=2017-04-01"
    original = az("original", ["rest", "--method", "get", "--url", url])
    off = route_toggle_payload(
        original["properties"], settings["workspaceResourceId"], enabled=False
    )
    on = route_toggle_payload(original["properties"], settings["workspaceResourceId"], enabled=True)
    workspace = az(
        "workspace",
        [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com"
            + settings["workspaceResourceId"]
            + "?api-version=2023-09-01",
        ],
    )
    if (
        workspace.get("tags", {}).get("project") != "AgentTrace"
        or "/resourcegroups/kb-agentdemo/" not in workspace["id"].lower()
    ):
        raise RuntimeError("managed_workspace_route_required")
    if args.apply and args.record_recovery:
        raise RuntimeError("choose_apply_or_record_recovery")
    if args.record_recovery:
        recorded = ROOT / "docs/evidence/graph-route-refresh-validation.json"
        if settings.get("last_route_refresh_at") and recorded.is_file():
            report = json.loads(recorded.read_text())
            if report.get("coverage_gap_recorded") and graph_route_enabled(original["properties"]):
                print(json.dumps({"recovery_already_recorded": True, "route_enabled": True}))
                return 0
        disabled = json.loads((directory / "refresh-disabled.private.json").read_text())
        restored = json.loads((directory / "refresh-enabled-readback.private.json").read_text())
        missing = (directory / "refresh-disabled-readback.error.private.txt").read_bytes()
        if (
            graph_route_enabled(disabled["properties"])
            or not graph_route_enabled(restored["properties"])
            or not graph_route_enabled(original["properties"])
            or b"ResourceNotFound" not in missing
            or disabled["properties"]["workspaceId"].lower()
            != settings["workspaceResourceId"].lower()
            or restored["properties"]["workspaceId"].lower()
            != settings["workspaceResourceId"].lower()
        ):
            raise RuntimeError("saved_restore_receipts_do_not_confirm_recovery")
        start = datetime.fromisoformat(settings["last_route_refresh_attempt_at"])
        end = datetime.fromtimestamp(
            (directory / "refresh-enabled-readback.private.json").stat().st_mtime, UTC
        )
        list_url = "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings?api-version=2017-04-01"
        before = json.loads((directory / "refresh-settings-before.private.json").read_text())
        after = az("settings-after", ["rest", "--method", "get", "--url", list_url])
        _, _, operator, _, _ = load(
            ROOT / "work/private/mail-ingestion/runtime.private.json", operator=True
        )
        gap = operator.gap(collector.source_ref, "graph_activity_route_refresh", started_at=start)
        with operator.database.connect() as connection:
            connection.execute(
                "UPDATE ingest_gaps SET disposition='unrecoverable',ended_at=%s WHERE gap_ref=%s",
                (end, UUID(str(gap))),
            )
        other_before = {
            v["name"]: v for v in before["value"] if v["name"] != "AgentTraceGraphActivity"
        }
        other_after = {
            v["name"]: v for v in after["value"] if v["name"] != "AgentTraceGraphActivity"
        }
        settings["last_route_refresh_at"] = end.isoformat()
        (directory / "logging-settings.private.json").write_text(json.dumps(settings, indent=2))
        report = {
            "executed_at": datetime.now(UTC).isoformat(),
            "recorded_from_saved_API_receipts": True,
            "disabled_write_confirmed": True,
            "disabled_readback_returned_not_found": True,
            "enabled_readback_confirmed": True,
            "current_enabled_state_independently_verified": True,
            "other_tenant_settings_preserved": other_before == other_after,
            "interval_seconds": round((end - start).total_seconds(), 2),
            "coverage_gap_recorded": True,
            "known_lost_events": None,
            "graph_delivery_proven_by_refresh": False,
            "email_mutations": 0,
            "refresh_operation_passed": other_before == other_after,
        }
        (ROOT / "docs/evidence/graph-route-refresh-validation.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps(report))
        return 0 if report["refresh_operation_passed"] else 1
    if settings.get("last_route_refresh_attempt_at"):
        print(json.dumps({"refresh_already_performed": True, "repeated_toggle_refused": True}))
        return 0
    print(
        json.dumps({"dedicated_route_reviewed": True, "apply": args.apply, "email_mutations": 0}),
        flush=True,
    )
    if not args.apply:
        return 0
    canary = json.loads((ROOT / "docs/evidence/graph-route-canary-validation.json").read_text())
    if not canary["workspace_ingestion_and_query_canary_passed"]:
        raise RuntimeError("destination_canary_must_pass_before_refresh")
    row_result = collector.transport.request(
        "POST",
        f"https://api.loganalytics.azure.com/v1/workspaces/{collector.workspace}/query",
        body={"query": "MicrosoftGraphActivityLogs | summarize Rows=count()"},
    )
    if row_result["tables"][0]["rows"][0][0]:
        print(json.dumps({"graph_records_already_present": True, "refresh_skipped": True}))
        return 0
    _, _, operator, _, _ = load(
        ROOT / "work/private/mail-ingestion/runtime.private.json", operator=True
    )
    with operator.database.connect() as connection:
        connection.execute("SELECT 1")
    list_url = "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings?api-version=2017-04-01"
    before = az("settings-before", ["rest", "--method", "get", "--url", list_url])
    for label, body in [("off", off), ("on", on)]:
        (directory / ("refresh-" + label + "-request.private.json")).write_text(json.dumps(body))
    start = datetime.now(UTC)
    settings["last_route_refresh_attempt_at"] = start.isoformat()
    (directory / "logging-settings.private.json").write_text(json.dumps(settings, indent=2))
    off_verified = False
    on_verified = False
    try:
        az(
            "disabled",
            [
                "rest",
                "--method",
                "put",
                "--url",
                url,
                "--body",
                "@" + str(directory / "refresh-off-request.private.json"),
            ],
        )
        state = az(
            "disabled-readback", ["rest", "--method", "get", "--url", url], allow_missing=True
        )
        off_verified = state.get("resource_absent", False) or not graph_route_enabled(
            state["properties"]
        )
        if not off_verified:
            raise RuntimeError("route_disable_not_confirmed")
        time.sleep(5)
    finally:
        for attempt in range(3):
            try:
                az(
                    "reenabled",
                    [
                        "rest",
                        "--method",
                        "put",
                        "--url",
                        url,
                        "--body",
                        "@" + str(directory / "refresh-on-request.private.json"),
                    ],
                )
                state = az("enabled-readback", ["rest", "--method", "get", "--url", url])
                on_verified = (
                    graph_route_enabled(state["properties"])
                    and state["properties"]["workspaceId"].lower()
                    == settings["workspaceResourceId"].lower()
                )
                if on_verified:
                    break
            except RuntimeError:
                if attempt == 2:
                    raise
                time.sleep(5)
    end = datetime.now(UTC)
    after = az("settings-after", ["rest", "--method", "get", "--url", list_url])
    other_before = {v["name"]: v for v in before["value"] if v["name"] != "AgentTraceGraphActivity"}
    other_after = {v["name"]: v for v in after["value"] if v["name"] != "AgentTraceGraphActivity"}
    gap = operator.gap(collector.source_ref, "graph_activity_route_refresh", started_at=start)
    with operator.database.connect() as connection:
        connection.execute(
            "UPDATE ingest_gaps SET disposition='unrecoverable',ended_at=%s WHERE gap_ref=%s",
            (end, UUID(str(gap))),
        )
    settings["last_route_refresh_at"] = end.isoformat()
    (directory / "logging-settings.private.json").write_text(json.dumps(settings, indent=2))
    report = {
        "executed_at": end.isoformat(),
        "disabled_readback_confirmed": off_verified,
        "enabled_readback_confirmed": on_verified,
        "other_tenant_settings_preserved": other_before == other_after,
        "interval_seconds": round((end - start).total_seconds(), 2),
        "coverage_gap_recorded": True,
        "known_lost_events": None,
        "graph_delivery_proven_by_refresh": False,
        "email_mutations": 0,
    }
    report["refresh_operation_passed"] = (
        off_verified and on_verified and other_before == other_after
    )
    (ROOT / "docs/evidence/graph-route-refresh-validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report))
    return 0 if report["refresh_operation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
