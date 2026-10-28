"""Private inference boundary; runtime processing never downloads a model."""

from dataclasses import dataclass, field
from typing import Protocol

from agenttrace_contracts import ContentAssessment, unknown_content


@dataclass(frozen=True)
class ContentSample:
    text: str = field(repr=False)
    language: str


class ContentScorer(Protocol):
    def assess(self, sample: ContentSample) -> ContentAssessment: ...


class UnavailableContentScorer:
    """Foundation behavior only; not an attempted or qualified statistical detector."""

    def assess(self, sample: ContentSample) -> ContentAssessment:
        if sample.language != "en":
            return unknown_content("unsupported_or_unestablished_content_language")
        return unknown_content()
