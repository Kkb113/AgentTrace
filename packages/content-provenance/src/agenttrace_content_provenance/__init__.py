"""Generation and inclusion must both be established for provenance claims."""

from agenttrace_contracts import ContentAssessment, unknown_content


def require_inclusion(
    provenance: ContentAssessment, *, inclusion_verified: bool
) -> ContentAssessment:
    if provenance.status == "verified_ai_content" and not inclusion_verified:
        return unknown_content("content_inclusion_not_established")
    return provenance
