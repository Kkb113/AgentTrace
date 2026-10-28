"""Application retention enforcement before raw evidence credentials or bytes are used."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .authorization import AccessDenied


@dataclass(frozen=True)
class RawEvidenceReference:
    reference: str
    mailbox: str
    captured_at: datetime
    expires_at: datetime

    def authorize(self, allowed_mailbox: str) -> None:
        now = datetime.now(UTC)
        if (
            self.mailbox != allowed_mailbox
            or self.captured_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.captured_at > now
            or self.expires_at > self.captured_at + timedelta(days=7)
            or not self.captured_at < self.expires_at
            or now >= self.expires_at
        ):
            raise AccessDenied("raw_evidence_denied_or_expired")


@dataclass(frozen=True)
class TransientEvidence:
    value: bytes = field(repr=False)


def read_retained_evidence(
    reference: RawEvidenceReference,
    *,
    allowed_mailbox: str,
    loader: Callable[[str], bytes],
) -> TransientEvidence:
    reference.authorize(allowed_mailbox)
    return TransientEvidence(loader(reference.reference))
