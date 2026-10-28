"""Inspect a real synthetic EML and unverified, operator-provided tool transcript.

This deliberately does not turn a later subject search into a verified execution
link. It supports an honest end-to-end unknown result when source evidence lacks IDs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .attribution import finding
from .mime import parse_mime
from .validation import InputError, digest, load_json, object_fields, read_bytes, text, timestamp


def inspect_synthetic_export(mime_path: Path, transcript_path: Path) -> dict:
    raw = read_bytes(mime_path)
    message = parse_mime(raw)
    subject = str(message.get("Subject", ""))
    if not subject.startswith("AgentTrace synthetic test:"):
        raise InputError("only_marked_synthetic_exports_allowed")
    transcript = object_fields(
        load_json(transcript_path),
        {
            "source",
            "send_operation",
            "send_result",
            "send_message_id",
            "send_request_id",
            "send_timestamp",
            "lookup_operation",
            "lookup",
        },
    )
    for key in ["source", "send_operation", "send_result", "lookup_operation"]:
        text(transcript[key])
    for key in ["send_message_id", "send_request_id", "send_timestamp"]:
        if transcript[key] is not None:
            text(transcript[key])
    lookup = object_fields(transcript["lookup"], {"message_id", "internet_message_id", "sent_at"})
    for value in lookup.values():
        text(value)
    timestamp(lookup["sent_at"])
    ids = message.get_all("Message-ID", [])
    if len(ids) != 1:
        raise InputError("message_id_missing_or_ambiguous")
    matches = str(ids[0]).strip() == lookup["internet_message_id"]
    declaration = str(message.get("x-ai-generated", ""))
    reasons = ["operator_transcript_is_not_authenticated_source_execution"]
    if not matches:
        reasons.append("sent_lookup_and_received_message_id_mismatch")
    if transcript["send_message_id"] is None and transcript["send_request_id"] is None:
        reasons.append("send_result_has_no_message_or_request_id")
    return {
        "schema_version": "1.0",
        "rule_version": "export-inspection/0.1.0",
        "environment": "synthetic_test_tenant",
        "observed_at": datetime.now(UTC).isoformat(),
        "validation_basis": "real_email_export_with_operator_supplied_unverified_source_transcript",
        "message_sha256": digest(raw),
        "findings": {
            "agent_send_attribution": finding("unknown", None, reasons),
            "content_assessment": finding(
                "unknown", None, ["statistical_content_experiment_not_run_by_evidence_spike"]
            ),
        },
        "supporting_observations": {
            "received_and_sent_lookup_internet_message_ids_match": matches,
            "send_response_contains_linking_id": bool(
                transcript["send_message_id"] or transcript["send_request_id"]
            ),
            "header_declaration_present": bool(declaration),
            "header_declaration_trust": "unverified",
            "source_reported_operation": transcript["send_operation"],
            "source_reported_sent_at": lookup["sent_at"],
            "actual_audit_availability_lag_seconds": None,
        },
        "limitation": "A matching later Sent Items lookup identifies a message copy but does not itself bind the earlier send execution. No verified verdict or measured audit lag is asserted.",
    }
