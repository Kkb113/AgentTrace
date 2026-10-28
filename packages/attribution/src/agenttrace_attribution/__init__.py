"""Typed boundary around the conservative feasibility attribution engine."""

from pathlib import Path
from typing import Any

from agenttrace_contracts import DetectionFindings

from agenttrace_feasibility.attribution import assess_bundle
from agenttrace_feasibility.validation import timestamp


def assess_authored_example(bundle: Path) -> DetectionFindings:
    result: dict[str, Any] = assess_bundle(
        bundle, bundle / "trust-profile.json", timestamp("2026-10-28T10:10:00Z")
    )
    raw = dict(result["decisions"][0]["findings"])
    content = dict(raw["content_assessment"])
    if content["status"] == "verified_ai_content":
        content["qualification"] = "provenance"
    raw["content_assessment"] = content
    return DetectionFindings.model_validate(raw)
