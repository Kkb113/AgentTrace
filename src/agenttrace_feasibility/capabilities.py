"""Explicitly read-only Azure/Microsoft 365 capability collection.

Raw responses are written only to an ignored private directory. This collector uses
the operator's existing Azure CLI session; it is not a product workload identity.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from .validation import InputError

SYNTHETIC_SUBJECT_PREFIX = "AgentTrace synthetic test:"


def azure_cli_prefix() -> list[str]:
    executable = shutil.which("az")
    if not executable:
        raise InputError("azure_cli_not_installed")
    path = Path(executable)
    if sys.platform == "win32" and path.suffix.lower() in {".cmd", ".bat"}:
        python = path.parent.parent / "python.exe"
        if not python.is_file():
            raise InputError("azure_cli_python_entrypoint_unavailable")
        # Never pass a Graph URI containing '&' through a Windows batch file.
        return [str(python), "-IBm", "azure.cli"]
    return [str(path)]


def run_read_only(arguments: list[str], subscription: str, timeout: int = 45) -> dict:
    allowed = arguments in [
        ["account", "show"],
        ["group", "show", "--name", "kb-agentdemo"],
        ["resource", "list", "--resource-group", "kb-agentdemo"],
    ]
    if arguments[:4] == ["rest", "--method", "get", "--url"] and len(arguments) == 5:
        uri = urlsplit(arguments[4])
        allowed_graph_queries = {
            "/v1.0/me": {"$select": ["id,mail,userPrincipalName"]},
            "/v1.0/subscribedSkus": {"$select": ["skuPartNumber,capabilityStatus,servicePlans"]},
            "/v1.0/me/licenseDetails": {"$select": ["skuPartNumber,servicePlans"]},
            "/v1.0/me/memberOf/microsoft.graph.directoryRole": {"$select": ["displayName"]},
            "/beta/servicePrincipals/microsoft.graph.agentIdentity": {
                "$top": ["1"],
                "$select": ["id"],
            },
            "/v1.0/me/messages": {
                "$top": ["5"],
                "$filter": [f"startswith(subject,'{SYNTHETIC_SUBJECT_PREFIX}')"],
                "$select": ["id,internetMessageId,sentDateTime,receivedDateTime,isDraft"],
            },
        }
        allowed = (
            uri.scheme == "https"
            and not uri.username
            and not uri.fragment
            and (
                (
                    uri.netloc == "graph.microsoft.com"
                    and parse_qs(uri.query) == allowed_graph_queries.get(uri.path)
                )
                or (
                    uri.netloc == "management.azure.com"
                    and uri.path == "/providers/microsoft.aadiam/diagnosticSettings"
                    and uri.query == "api-version=2017-04-01"
                )
            )
        )
    if not allowed:
        raise InputError("azure_operation_not_allowlisted")
    command = [
        *azure_cli_prefix(),
        *arguments,
        "--subscription",
        subscription,
        "--output",
        "json",
        "--only-show-errors",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=timeout, shell=False
        )
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "reason": "request_timeout"}
    if completed.returncode:
        error = completed.stderr.lower()
        reason = (
            "access_denied"
            if any(
                s in error
                for s in [
                    "forbidden",
                    "authorizationfailed",
                    "accessdenied",
                    "insufficient privileges",
                ]
            )
            else "request_failed"
        )
        return {"status": "unavailable", "reason": reason}
    try:
        return {"status": "observed", "response": json.loads(completed.stdout)}
    except json.JSONDecodeError:
        return {"status": "unavailable", "reason": "non_json_response"}


def graph_uri(path: str, query: dict[str, str] | None = None, version: str = "v1.0") -> str:
    return f"https://graph.microsoft.com/{version}/{path}" + (
        "?" + urlencode(query) if query else ""
    )


def collect_capabilities(subscription: str, resource_group: str, output_dir: Path) -> dict:
    try:
        uuid.UUID(subscription)
    except ValueError as exc:
        raise InputError("invalid_subscription_id") from exc
    if resource_group != "kb-agentdemo":
        raise InputError("explicit_subscription_and_required_resource_group_needed")
    # Both raw and sanitized outputs go here; publishing is a separate reviewed step.
    if not output_dir.resolve().is_relative_to(Path.cwd().resolve() / "work" / "private"):
        raise InputError("private_output_directory_required")
    checks = {
        "subscription_context": ["account", "show"],
        "resource_group": ["group", "show", "--name", resource_group],
        "existing_resources": ["resource", "list", "--resource-group", resource_group],
        "operator_identity": [
            "rest",
            "--method",
            "get",
            "--url",
            graph_uri("me", {"$select": "id,mail,userPrincipalName"}),
        ],
        "tenant_licenses": [
            "rest",
            "--method",
            "get",
            "--url",
            graph_uri("subscribedSkus", {"$select": "skuPartNumber,capabilityStatus,servicePlans"}),
        ],
        "operator_licenses": [
            "rest",
            "--method",
            "get",
            "--url",
            graph_uri("me/licenseDetails", {"$select": "skuPartNumber,servicePlans"}),
        ],
        "operator_directory_roles": [
            "rest",
            "--method",
            "get",
            "--url",
            graph_uri("me/memberOf/microsoft.graph.directoryRole", {"$select": "displayName"}),
        ],
        "agent_identity_endpoint": [
            "rest",
            "--method",
            "get",
            "--url",
            graph_uri(
                "servicePrincipals/microsoft.graph.agentIdentity",
                {"$top": "1", "$select": "id"},
                "beta",
            ),
        ],
        "synthetic_message_read": [
            "rest",
            "--method",
            "get",
            "--url",
            graph_uri(
                "me/messages",
                {
                    "$top": "5",
                    "$filter": f"startswith(subject,'{SYNTHETIC_SUBJECT_PREFIX}')",
                    "$select": "id,internetMessageId,sentDateTime,receivedDateTime,isDraft",
                },
            ),
        ],
        "graph_log_diagnostic_settings": [
            "rest",
            "--method",
            "get",
            "--url",
            "https://management.azure.com/providers/microsoft.aadiam/diagnosticSettings?api-version=2017-04-01",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, arguments in checks.items():
        results[name] = run_read_only(arguments, subscription)
        print(f"{name}: {results[name]['status']}", flush=True)
    group_response = results["resource_group"].get("response", {})
    if group_response.get("name") != resource_group:
        raise InputError("required_resource_group_not_verified")
    raw = {"collected_at": datetime.now(UTC).isoformat(), "checks": results}
    (output_dir / "tenant-capabilities.private.json").write_text(
        json.dumps(raw, indent=2), encoding="utf-8"
    )
    skus = results["tenant_licenses"].get("response", {}).get("value", [])
    enabled_plans = {
        p["servicePlanName"]
        for s in skus
        if s.get("capabilityStatus") == "Enabled"
        for p in s.get("servicePlans", [])
        if p.get("provisioningStatus") == "Success"
    }
    diagnostics = results["graph_log_diagnostic_settings"].get("response", {}).get("value", [])
    enabled_graph_logs = any(
        (
            log.get("category") == "MicrosoftGraphActivityLogs"
            or log.get("categoryGroup") == "allLogs"
        )
        and log.get("enabled") is True
        for entry in diagnostics
        for log in entry.get("properties", {}).get("logs", [])
    )
    summary = {
        "collected_at": raw["collected_at"],
        "collection_mode": "read_only_existing_operator_session",
        "resource_group_verified": True,
        "resource_group_metadata_location": group_response.get("location"),
        "new_resources_created": 0,
        "checks": {
            k: {key: value for key, value in v.items() if key != "response"}
            for k, v in results.items()
        },
        "observations": {
            "entra_p1_or_p2_tenant_plan_observed": bool(
                {"AAD_PREMIUM", "AAD_PREMIUM_P2"} & enabled_plans
            )
            if skus
            else None,
            "exchange_tenant_plan_observed": any(
                p in enabled_plans for p in ["EXCHANGE_S_ENTERPRISE", "EXCHANGE_S_STANDARD"]
            )
            if skus
            else None,
            "graph_activity_logging_enabled": enabled_graph_logs
            if results["graph_log_diagnostic_settings"]["status"] == "observed"
            else None,
            "matching_synthetic_messages_returned": len(
                results["synthetic_message_read"].get("response", {}).get("value", [])
            )
            if results["synthetic_message_read"]["status"] == "observed"
            else None,
            "exchange_audit_enablement": "not_verified_requires_exchange_admin_evidence",
            "actual_audit_availability_lag": "not_measured_requires_linked_live_observations",
            "addin_authentication": "documented_candidate_not_runtime_tested",
        },
        "privacy": "No ordinary email body was requested. Raw identifiers and tenant responses stay in ignored private output.",
    }
    (output_dir / "tenant-capabilities.summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary
