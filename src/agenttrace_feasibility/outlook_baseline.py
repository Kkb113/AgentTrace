"""Frozen Outlook production requirements; no mailbox runtime or evidence promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .validation import InputError, canonical_bytes, load_json

ROOT = Path(__file__).resolve().parents[2]


class FrozenRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, hide_input_in_errors=True)


class Category(FrozenRecord):
    name: Literal["AI Agent", "Human", "Unknown"]
    color: Literal["red", "green", "yellow"]
    preset: Literal["preset0", "preset4", "preset3"]


class OutlookBaseline(FrozenRecord):
    schema_version: Literal["1.0"]
    profile: Literal["outlook_native_production_baseline"]
    categories: tuple[Category, Category, Category]
    receiving_routes: tuple[Literal["gmail_to_outlook"], Literal["outlook_to_outlook"]]
    clients: tuple[Literal["outlook_web"], Literal["new_outlook_windows"]]
    activation: Literal["record_utc_on_first_production_start"]
    backfill: Literal["explicit_bounded_operator_request_only"]
    category_collision: Literal["stop_until_owner_enrolls_or_chooses_new_names"]
    category_lifetime_days: Literal[30]
    raw_retention_days: Literal[7]
    decision_retention_days: Literal[30]
    qualification_data: Literal["synthetic_only"]
    live_diagnostic_access: Literal["owner_authorized_incoming_metadata_only"]
    unattended_data_boundary: Literal["must_be_recorded_before_enablement"]
    host: Literal["designated_always_on_windows_host_not_yet_enrolled"]
    state: Literal["planned_local_sqlite_single_host"]
    default_category: Literal["Unknown"]
    complete_inspection_no_automation_category: Literal["Human"]
    incomplete_inspection_category: Literal["Unknown"]
    human_result_basis: Literal["inferred_manual_client_not_proof_of_executor"]
    untrusted_declaration_category: Literal["Unknown"]
    generic_api_category: Literal["Unknown"]
    non_ai_automation_category: Literal["Unknown"]
    human_rule_status: Literal["policy_feasible_accuracy_qualification_pending"]
    demo_predictions_eligible_for_write: Literal[False]
    category_writes_enabled: Literal[False]
    new_permissions_authorized: Literal[False]
    writer_permission_proposal: Literal["mailbox_scoped_Application_Mail.ReadWrite"]
    setup_permission_proposal: Literal["manual_or_temporary_MailboxSettings.ReadWrite"]
    annotation_ownership: Literal["enrolled_ids_names_colors_only"]
    no_send_or_draft_execution: Literal[True]
    no_body_or_attachment_analysis: Literal[True]
    no_standalone_application: Literal[True]
    azure_resource_group: Literal["kb-agentdemo"]
    azure_region: Literal["eastus"]
    new_cloud_resources_required: Literal[False]
    positive_agent_fpr_upper_bound: float = Field(ge=0.001, le=0.001)
    confidence_level: float = Field(ge=0.95, le=0.95)
    supported_agent_recall_target: float = Field(ge=0.99, le=0.99)
    supported_agent_positive_minimum: Literal[1000]
    false_human_upper_bound: float = Field(ge=0.001, le=0.001)
    qualification_status: Literal["not_measured"]

    @model_validator(mode="after")
    def category_mapping(self) -> OutlookBaseline:
        actual = [(c.name, c.color, c.preset) for c in self.categories]
        if actual != [
            ("AI Agent", "red", "preset0"),
            ("Human", "green", "preset4"),
            ("Unknown", "yellow", "preset3"),
        ]:
            raise ValueError("frozen_category_mapping_mismatch")
        return self


def read_baseline(path: Path) -> OutlookBaseline:
    return OutlookBaseline.model_validate_json(canonical_bytes(load_json(path)))


def schema_text() -> str:
    return json.dumps(OutlookBaseline.model_json_schema(), indent=2, sort_keys=True) + "\n"


def verify(root: Path) -> dict[str, object]:
    baseline = read_baseline(root / "config/outlook-production-baseline.json")
    schema = root / "packages/contracts/schemas/outlook-production-baseline.schema.json"
    if schema.read_text(encoding="utf-8") != schema_text():
        raise InputError("outlook_baseline_schema_stale")
    archive = load_json(root / "config/outlook-demo-baseline.json")
    paths = {
        "scripts/watch-incoming-mail.py",
        "src/agenttrace_feasibility/mail_monitor.py",
        "tests/test_mail_monitor.py",
    }
    if (
        archive.get("profile") != "archived_experimental_demo"
        or archive.get("production_write_eligible") is not False
        or set(archive.get("source_sha256", {})) != paths
    ):
        raise InputError("demo_archive_invalid")
    for name, expected in archive["source_sha256"].items():
        actual = hashlib.sha256((root / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            raise InputError("archived_demo_source_changed")
    return {
        "profile": baseline.profile,
        "baseline_sha256": hashlib.sha256(
            canonical_bytes(baseline.model_dump(mode="json"))
        ).hexdigest(),
        "schema_current": True,
        "demo_archive_current": True,
        "category_writes_enabled": baseline.category_writes_enabled,
        "human_capability": baseline.human_rule_status,
        "qualification_status": baseline.qualification_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-schema", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.export_schema:
            read_baseline(ROOT / "config/outlook-production-baseline.json")
            (
                ROOT / "packages/contracts/schemas/outlook-production-baseline.schema.json"
            ).write_text(schema_text(), encoding="utf-8", newline="\n")
        print(json.dumps(verify(ROOT), sort_keys=True))
        return 0
    except (InputError, ValidationError, OSError, ValueError):
        print(json.dumps({"error": "outlook_baseline_invalid_or_schema_stale"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
