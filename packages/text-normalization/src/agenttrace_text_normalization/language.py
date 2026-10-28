"""Offline language eligibility, independent of AI origin or agent execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock

from langdetect.detector_factory import (  # type: ignore[import-untyped]
    PROFILES_DIRECTORY,
    DetectorFactory,
)


@dataclass(frozen=True)
class LanguageAssessment:
    language: str
    eligible_language: bool
    reason: str


class EnglishIdentifier:
    def __init__(self) -> None:
        self.factory = DetectorFactory()
        self.factory.seed = 0
        self.factory.load_profile(PROFILES_DIRECTORY)
        self.lock = Lock()

    def assess(self, text: str) -> LanguageAssessment:
        words = re.findall(r"\b[^\W\d_]+(?:['’-][^\W\d_]+)*\b", text)
        if len(words) < 20:
            return LanguageAssessment("unknown", False, "insufficient_language_evidence")
        letters = [char for char in text if char.isalpha()]
        latin = sum(char.isascii() for char in letters)
        if not letters or latin / len(letters) < 0.95:
            return LanguageAssessment("unknown", False, "unsupported_or_mixed_script")
        # Whole text plus substantive paragraphs. A non-English paragraph cannot
        # disappear inside a larger English majority. Scores are language scores.
        samples = [text, *[line for line in text.splitlines() if len(line.split()) >= 12]]
        try:
            with self.lock:
                for sample in samples:
                    detector = self.factory.create()
                    detector.append(sample)
                    candidates = detector.get_probabilities()
                    if not candidates or candidates[0].lang != "en" or candidates[0].prob < 0.99:
                        return LanguageAssessment(
                            "unknown", False, "unsupported_or_uncertain_language"
                        )
        except Exception:
            return LanguageAssessment("unknown", False, "language_identification_failed")
        return LanguageAssessment("en", True, "english_language_evidence")
