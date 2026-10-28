"""Conservative evidence replay for two independent detection findings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .evidence import MessageObservation, VerifiedRecord, load_messages, load_profile, verify_record
from .validation import InputError, canonical_bytes, digest, load_json, record_list


def finding(
    status: str, flagged: bool | None, reasons: list[str], records: list[str] | None = None
) -> dict:
    return {
        "status": status,
        "flagged": flagged,
        "reason_codes": sorted(set(reasons)),
        "evidence_refs": sorted(records or []),
    }


def _agent_finding(message: MessageObservation, records: list[VerifiedRecord]) -> dict:
    sends = [
        r
        for r in records
        if r.kind == "send_execution"
        and r.facts["action"] == "send"
        and r.facts["outcome"] == "completed"
    ]
    if message.state not in {"sent", "received"}:
        return finding("unknown", None, ["completed_message_observation_missing"])
    if not sends:
        return finding("unknown", None, ["completed_send_evidence_missing"])
    executors = {
        (r.facts["executor_type"], r.facts["actor_ref"], r.facts["execution_id"]) for r in sends
    }
    if len(executors) != 1:
        return finding("unknown", None, ["conflicting_send_executors"])
    executor_type = sends[0].facts["executor_type"]
    refs = [r.evidence_id for r in sends]
    if executor_type == "ai_agent":
        return finding("verified_agent", True, ["trusted_agent_send_and_exact_message_link"], refs)
    if executor_type in {"human", "non_ai_application"}:
        return finding(
            "no_agent_observed_in_monitored_path",
            False,
            ["observed_non_agent_send_is_bounded_evidence"],
            refs,
        )
    return finding("unknown", None, ["executor_type_unresolved"], refs)


def _content_finding(message: MessageObservation, records: list[VerifiedRecord]) -> dict:
    if message.body_language != "en":
        return finding("unknown", None, ["unsupported_or_unestablished_content_language"])
    included = [r for r in records if r.kind == "content_inclusion"]
    supported = [
        r
        for r in included
        if r.facts["inclusion_method"] == "authenticated_transfer_lineage"
        and r.facts["material_origin"] == "new_generated_output"
        and r.facts["operation"]
        in {"draft_generation", "substantial_rewrite", "translation_into_english"}
    ]
    if supported and message.body:
        return finding(
            "verified_ai_content",
            True,
            ["trusted_generation_and_inclusion_link"],
            [r.evidence_id for r in supported],
        )
    if included and all(
        r.facts["operation"] == "basic_correction"
        and r.facts["inclusion_method"] == "authenticated_transfer_lineage"
        and r.facts["material_origin"] == "human_input_with_basic_correction"
        for r in included
    ):
        return finding(
            "no_ai_signal_detected",
            False,
            ["basic_correction_observed_only_in_monitored_path"],
            [r.evidence_id for r in included],
        )
    reason = "statistical_content_experiment_not_run_by_evidence_spike"
    if not message.body:
        reason = "plain_text_body_unavailable"
    elif included:
        reason = "content_origin_or_inclusion_insufficient"
    return finding("unknown", None, [reason])


def assess_bundle(bundle: Path, profile_path: Path, as_of: datetime) -> dict:
    profile = load_profile(profile_path)
    messages = load_messages(bundle, profile)
    envelopes = record_list(load_json(bundle / "evidence.json"))
    results = []
    for message in messages:
        if (
            message.binding["tenant_ref"] != profile["tenant_ref"]
            or message.binding["mailbox_ref"] not in profile["mailbox_refs"]
        ):
            raise InputError("outside_authorized_scope")
        records: list[VerifiedRecord] = []
        rejected: dict[str, list[str]] = {"send_execution": [], "content_inclusion": []}
        seen: dict[str, tuple[str, bytes]] = {}
        for envelope in envelopes:
            if not isinstance(envelope, dict) or not isinstance(envelope.get("record"), dict):
                raise InputError("invalid_evidence_envelope")
            binding = envelope["record"].get("binding")
            if not isinstance(binding, dict):
                raise InputError("invalid_evidence_binding")
            # This is only a candidate lookup, never proof of message identity.
            if binding.get("immutable_id") != message.binding["immutable_id"]:
                continue
            kind = envelope["record"].get("kind")
            if not isinstance(kind, str) or kind not in rejected:
                raise InputError("unsupported_evidence_kind")
            try:
                verified = verify_record(envelope, message, profile, as_of)
                encoded = canonical_bytes(envelope["record"])
                if verified.evidence_id in seen:
                    previous_kind, previous_bytes = seen[verified.evidence_id]
                    if previous_bytes != encoded:
                        rejected[previous_kind].append("conflicting_reuse_of_evidence_id")
                        raise InputError("conflicting_reuse_of_evidence_id")
                    continue  # Exact replay is idempotent, not a new decision or sample.
                seen[verified.evidence_id] = (kind, encoded)
                records.append(verified)
            except InputError as exc:
                rejected[kind].append(str(exc))
        # Content failures must never change a valid send finding, and vice versa.
        agent = (
            finding("unknown", None, ["send_evidence_import_rejected", *rejected["send_execution"]])
            if rejected["send_execution"]
            else _agent_finding(message, records)
        )
        content = (
            finding(
                "unknown",
                None,
                ["content_evidence_import_rejected", *rejected["content_inclusion"]],
            )
            if rejected["content_inclusion"]
            else _content_finding(message, records)
        )
        lag = [(r.emitted_at - r.occurred_at).total_seconds() for r in records]
        results.append(
            {
                "message_ref": message.message_ref,
                "findings": {"agent_send_attribution": agent, "content_assessment": content},
                "evidence_summary": {
                    "verified_records": len(records),
                    "rejected_records": sum(len(items) for items in rejected.values()),
                    "source_emission_lag_seconds": lag,
                    "lag_basis": "source_record_timestamps_not_a_measurement_of_microsoft_feed_availability",
                },
            }
        )
    return {
        "schema_version": "1.0",
        "rule_version": "evidence-spike/0.1.0",
        "environment": profile["environment"],
        "as_of": as_of.isoformat(),
        "evidence_bundle_sha256": digest(
            canonical_bytes(
                {"observations": load_json(bundle / "observations.json"), "evidence": envelopes}
            )
        ),
        "validation_basis": "authored_contract_examples_not_independent_tenant_validation"
        if profile["environment"] == "contract_example"
        else "imported_evidence_requires_independent_operator_and_source_review",
        "decisions": results,
    }
