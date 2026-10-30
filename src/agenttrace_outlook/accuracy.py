"""Frozen-window, split-aware sender studies with explicit independent-evidence gates."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from pathlib import Path
from typing import Any

from agenttrace_feasibility.validation import canonical_bytes

from .accuracy_contracts import (
    AccuracyDataset,
    DetectorPacket,
    EvaluationCase,
    Split,
    review_binding,
)
from .accuracy_io import asset_bytes, decode, detector_digest, digest, policy_digest
from .accuracy_metrics import metrics
from .accuracy_replay import replay
from .errors import OutlookError

GROUPS = ("sender", "workflow", "thread", "template", "source", "independence_cluster")
REQUIRED_FAMILIES = {
    "manual_client",
    "manual_ai_text",
    "approved_agent",
    "autonomous_agent",
    "ordinary_automation",
    "uninstrumented_agent",
}


def _review_issues(dataset: AccuracyDataset, case: EvaluationCase, now: datetime) -> list[str]:
    issues = []
    registry = {r.reviewer_ref: r for r in dataset.reviewers}
    if case.basis != "independent_action_history":
        issues.append("not_independent_accuracy_data")
    if case.actor == "unresolved" or case.time_basis == "collection_only":
        issues.append("action_truth_or_time_unresolved")
    if (
        ("ordinary_automation" in case.families and case.actor != "non_ai_automation")
        or (
            "approved_agent" in case.families
            and (case.actor != "ai_agent" or case.approval != "approved")
        )
        or (
            "autonomous_agent" in case.families
            and (case.actor != "ai_agent" or case.approval != "autonomous")
        )
    ):
        issues.append("scenario_family_conflicts_with_action_truth")
    valid = []
    for review in case.reviews:
        who = registry.get(review.reviewer_ref)
        if (
            who is None
            or who.kind != "human"
            or not who.independent_of_detector
            or review.reviewer_ref == case.creator_ref
            or not review.blind_to_predictions
            or not review.action_source_verified
            or not review.capture_custody_verified
            or review.reviewed_at > now
            or review.reviewed_at
            < max(case.input.collected_at, case.action.collected_at, case.rights.collected_at)
            or (review.input_sha256, review.action_sha256, review.rights_sha256)
            != (case.input.sha256, case.action.sha256, case.rights.sha256)
            or review.case_sha256 != review_binding(case)
        ):
            continue
        valid.append(review)
    if len({r.reviewer_ref for r in valid}) != len(valid):
        issues.append("reviewer_reused_within_case")
    regular = [r for r in valid if not r.adjudication]
    adjudicated = [r for r in valid if r.adjudication]
    if not regular:
        issues.append("independent_action_review_missing")
    elif len({r.actor for r in regular}) > 1:
        if len(regular) != 2 or len(adjudicated) != 1 or adjudicated[0].actor != case.actor:
            issues.append("action_review_disagreement_unresolved")
    elif any(r.actor != case.actor for r in regular):
        issues.append("label_does_not_match_review")
    return issues


def _message_text(data: bytes) -> str:
    message = BytesParser(policy=policy.default).parsebytes(data)
    part = message.get_body(preferencelist=("plain",)) if message.is_multipart() else message
    if part is None or part.get_content_type() != "text/plain":
        raise OutlookError("study_plain_text_unavailable_for_leakage")
    content = part.get_content()
    if not isinstance(content, str):
        raise OutlookError("study_plain_text_unavailable_for_leakage")
    return " ".join(re.findall(r"\w+", content.lower()))


def inspect_study(root: Path, dataset: AccuracyDataset, now: datetime) -> dict[str, Any]:
    """No detector calls. Review/rights/hash/retention/leakage checks precede any scoring."""
    issues: set[str] = set()
    if dataset.detector_sha256 != detector_digest():
        issues.add("detector_freeze_mismatch")
    if dataset.policy_sha256 != policy_digest():
        issues.add("policy_freeze_mismatch")
    packets: dict[str, DetectorPacket] = {}
    case_issues: dict[str, list[str]] = {}
    split_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    text_groups: dict[str, list[str]] = defaultdict(list)
    near_buckets: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
    near_pairs: set[tuple[str, str]] = set()
    parent = {c.case_ref: c.case_ref for c in dataset.cases}
    splits = {c.case_ref: c.split for c in dataset.cases}
    total_bytes = 0

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def join(left: str, right: str) -> None:
        parent[find(right)] = find(left)

    seen_clusters: dict[tuple[str, str], str] = {}
    for case in dataset.cases:
        errors = _review_issues(dataset, case, now)
        assets = [case.input, case.action, case.rights, *[r.attestation for r in case.reviews]]
        if case.message:
            assets.append(case.message)
        contents = {}
        try:
            for asset in assets:
                data = asset_bytes(root, asset, now)
                total_bytes += len(data)
                if total_bytes > 128 * 1024 * 1024:
                    raise OutlookError("study_total_input_budget_exceeded")
                contents[asset.path] = data
            for review in case.reviews:
                attestation = decode(contents[review.attestation.path])
                expected = review.model_dump(mode="json", exclude={"attestation"})
                if attestation != expected:
                    errors.append("review_attestation_does_not_match_record")
            packet = DetectorPacket.model_validate_json(
                canonical_bytes(decode(contents[case.input.path]))
            )
            if case.prepared_at > packet.observation.received_at or case.prepared_at > now:
                errors.append("source_time_inconsistent")
            packets[case.case_ref] = packet
            for frame in packet.frames:
                headers = (frame.snapshot or {}).get("internetMessageHeaders", [])
                if not isinstance(headers, list):
                    continue  # Failed inspection remains a scored Unknown, not a dropped actor.
                addresses = getaddresses(
                    [
                        h["value"]
                        for h in headers
                        if isinstance(h, dict)
                        and str(h.get("name", "")).lower() == "from"
                        and isinstance(h.get("value"), str)
                    ]
                )
                if len(addresses) == 1 and addresses[0][1]:
                    split_groups[("observed_sender", digest(addresses[0][1].lower().encode()))].add(
                        case.split
                    )
            provider_key = digest(
                canonical_bytes(
                    [
                        packet.observation.scope.model_dump(mode="json"),
                        packet.observation.message_id,
                    ]
                )
            )
            split_groups[("provider_message", provider_key)].add(case.split)
            if ("provider_message", provider_key) in seen_clusters:
                join(seen_clusters[("provider_message", provider_key)], case.case_ref)
            seen_clusters[("provider_message", provider_key)] = case.case_ref
            route_supported = (
                case.source_family == "claude_m365_mcp"
                and case.route == "outlook_to_outlook"
                and any(e.scope == packet.observation.scope for e in dataset.enrollments)
            )
            if case.supported_agent_path != route_supported:
                errors.append("supported_path_scope_mismatch")
            if case.message:
                text = _message_text(contents[case.message.path])
                text_hash = digest(text.encode())
                if case.text_sha256 is not None and case.text_sha256 != text_hash:
                    errors.append("message_text_hash_mismatch")
                text_groups[text_hash].append(case.case_ref)
                words = text.split()
                shingles = {" ".join(words[i : i + 3]) for i in range(max(0, len(words) - 2))}
                fingerprints = sorted(digest(s.encode()) for s in shingles)[:8]
                for fingerprint in fingerprints:
                    for previous, other in near_buckets[fingerprint]:
                        left, right = sorted((previous, case.case_ref))
                        pair = (left, right)
                        if pair in near_pairs:
                            continue
                        near_pairs.add(pair)
                        if len(near_pairs) > 200000:
                            raise OutlookError("study_near_duplicate_budget_exceeded")
                        if len(shingles & other) / max(1, len(shingles | other)) >= 0.85:
                            join(previous, case.case_ref)
                            if splits[previous] != case.split:
                                issues.add("near_duplicate_across_splits")
                    near_buckets[fingerprint].append((case.case_ref, shingles))
            else:
                errors.append("independent_message_leakage_check_unavailable")
        except (ValueError, TypeError, KeyError, OutlookError):
            errors.append("source_assets_or_packet_invalid")
        for group in GROUPS:
            value = getattr(case.groups, group)
            split_groups[(group, value)].add(case.split)
            if group in {"template", "independence_cluster"}:
                identity = (group, value)
                if identity in seen_clusters:
                    join(seen_clusters[identity], case.case_ref)
                seen_clusters[identity] = case.case_ref
        for kind, value in (("input", case.input.sha256), ("action", case.action.sha256)):
            split_groups[(kind, value)].add(case.split)
            if (kind, value) in seen_clusters:
                join(seen_clusters[(kind, value)], case.case_ref)
            seen_clusters[(kind, value)] = case.case_ref
        case_issues[case.case_ref] = sorted(set(errors))
    for refs in text_groups.values():
        if len({splits[r] for r in refs}) > 1:
            issues.add("duplicate_text_across_splits")
        for ref in refs[1:]:
            join(refs[0], ref)
    if any(len(values) > 1 for values in split_groups.values()):
        issues.add("group_or_source_leakage_across_splits")
    boundaries = []
    for split in ("development", "calibration", "evaluation"):
        times = [c.prepared_at for c in dataset.cases if c.split == split]
        if times:
            boundaries.append((min(times), max(times)))
    if dataset.usage == "curator_study" and len(boundaries) != 3:
        issues.add("three_disjoint_time_splits_required")
    if any(left[1] >= right[0] for left, right in zip(boundaries, boundaries[1:])):
        issues.add("time_split_order_invalid")
    return {
        "issues": sorted(issues),
        "case_issues": case_issues,
        "packets": packets,
        "clusters": {ref: find(ref) for ref in parent},
        "near_duplicate_pairs_checked": len(near_pairs),
    }


def run_study(
    root: Path,
    dataset: AccuracyDataset,
    split: Split,
    now: datetime,
    *,
    locked_access_verified: bool = False,
) -> dict[str, Any]:
    if split == "evaluation" and not locked_access_verified:
        raise OutlookError("locked_evaluation_requires_curator_release")
    inspection = inspect_study(root, dataset, now)
    enrollments = {e.scope.model_dump_json(): e for e in dataset.enrollments}
    rows = []
    for case in dataset.cases:
        if case.split != split:
            continue
        packet = inspection["packets"].get(case.case_ref)
        errors = inspection["case_issues"][case.case_ref]
        for window, hours in (("initial", 2), ("late", 24)):
            at = packet.observation.observed_at + timedelta(hours=hours) if packet else now
            not_mature = now < at
            assessment = (
                replay(packet, enrollments.get(packet.observation.scope.model_dump_json()), at)
                if packet and not not_mature
                else None
            )
            rows.append(
                {
                    "case_ref": case.case_ref,
                    "window": window,
                    "actor": case.actor,
                    "category": assessment.category if assessment else "Unknown",
                    "rule": assessment.rule_version if assessment else None,
                    "reasons": list(assessment.reason_codes)
                    if assessment
                    else ["window_not_mature_or_input_unavailable"],
                    "accuracy_eligible": not errors and not inspection["issues"] and not not_mature,
                    "quarantine": [*errors, *(["window_not_mature"] if not_mature else [])],
                    "supported_agent_path": case.supported_agent_path,
                    "independence_cluster": inspection["clusters"][case.case_ref],
                    "route": case.route,
                    "source_family": case.source_family,
                    "population": case.population,
                    "approval": case.approval,
                    "families": list(case.families),
                }
            )
    windows = {}
    for window in ("initial", "late"):
        selected = [r for r in rows if r["window"] == window]
        supported = [r for r in selected if r["supported_agent_path"]]
        by_population = {}
        for population in dataset.enabled_populations:
            population_rows = [r for r in selected if r["population"] == population]
            all_metrics = metrics(population_rows)
            supported_metrics = metrics([r for r in population_rows if r["supported_agent_path"]])
            upper = all_metrics["false_positive_one_sided_95_upper"]
            observed_recall = supported_metrics["recall"]
            families = {f for r in population_rows if r["accuracy_eligible"] for f in r["families"]}
            g1 = (
                upper is not None
                and upper <= 0.001
                and any(
                    r["accuracy_eligible"] and r["actor"] == "non_ai_automation"
                    for r in population_rows
                )
            )
            g2 = (
                supported_metrics["independent_positive_clusters"] >= 1000
                and observed_recall is not None
                and observed_recall >= 0.99
            )
            coverage = {
                "manual_client",
                "manual_ai_text",
                "ordinary_automation",
                "approved_agent",
                "autonomous_agent",
            } <= families
            by_population[population] = {
                "all_paths": all_metrics,
                "supported_paths": supported_metrics,
                "G1": g1,
                "G2": g2,
                "required_population_families_present": coverage,
            }
        windows[window] = {
            "all_paths": metrics(selected),
            "supported_paths": metrics(supported),
            "by_population": by_population,
            "by_route": {
                key: metrics([r for r in selected if r["route"] == key])
                for key in sorted({r["route"] for r in selected})
            },
            "by_source": {
                key: metrics([r for r in selected if r["source_family"] == key])
                for key in sorted({r["source_family"] for r in selected})
            },
            "by_approval": {
                key: metrics([r for r in selected if r["approval"] == key])
                for key in sorted({r["approval"] for r in selected})
            },
        }
    initial = windows["initial"]
    qualified = bool(
        dataset.usage == "curator_study"
        and split == "evaluation"
        and locked_access_verified
        and not inspection["issues"]
        and rows
        and all(r["accuracy_eligible"] for r in rows)
        and all(
            p["G1"] and p["G2"] and p["required_population_families_present"]
            for p in initial["by_population"].values()
        )
    )
    return {
        "schema_version": "1.0",
        "study_ref": dataset.study_ref,
        "executed_at": now.isoformat(),
        "detector_sha256": detector_digest(),
        "policy_sha256": policy_digest(),
        "dataset_sha256": digest(canonical_bytes(dataset.model_dump(mode="json"))),
        "split": split,
        "issues": inspection["issues"],
        "case_count": len(rows) // 2,
        "near_duplicate_pairs_checked": inspection["near_duplicate_pairs_checked"],
        "windows": windows,
        "rows": rows,
        "locked_access_verified": locked_access_verified,
        "release_accuracy_qualified": qualified,
        "release_status": "eligible_for_independent_release_review"
        if qualified
        else "pilot_only_or_unqualified",
        "declared_blind_spots": list(dataset.declared_blind_spots),
        "accepted_copied_id_replacement_risk": True,
        "human_capable_is_controller_proof": False,
        "category_writes_enabled": False,
        "email_mutations": 0,
    }
