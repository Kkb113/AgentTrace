"""Explicit capabilities for mailbox reads, transient bodies and outbound requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from .authorization import AccessDenied, audit


@dataclass(frozen=True)
class EvidenceCapability:
    mailbox: str
    message_id: str = field(repr=False)
    version: str
    expires_at: datetime
    synthetic: bool = True

    def require_current(self, now: datetime | None = None) -> None:
        instant = now or datetime.now(UTC)
        if (
            not self.synthetic
            or self.expires_at.tzinfo is None
            or not instant < self.expires_at <= instant + timedelta(days=7)
            or not self.message_id
            or not self.version
        ):
            raise AccessDenied("evidence_capability_invalid_or_expired")


@dataclass(frozen=True)
class MailboxReadPolicy:
    mailbox: str
    message_ids: frozenset[str] = field(repr=False)

    def authorize(self, capability: EvidenceCapability) -> None:
        capability.require_current()
        if capability.mailbox != self.mailbox or capability.message_id not in self.message_ids:
            audit("mailbox_read", "denied")
            raise AccessDenied("mailbox_or_message_not_enrolled")


def require_allowed_egress(url: str, *, component: str) -> None:
    """Content processing has no HTTP egress; collectors have fixed Microsoft origins."""
    parsed = urlsplit(url)
    hosts = {
        "mail_collector": {"graph.microsoft.com", "login.microsoftonline.com"},
        "audit_collector": {"graph.microsoft.com", "login.microsoftonline.com"},
        "api": {"login.microsoftonline.com"},
        "content": set(),
    }
    if (
        component not in hosts
        or parsed.scheme != "https"
        or parsed.hostname not in hosts[component]
        or parsed.port not in {None, 443}
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise AccessDenied("outbound_destination_denied")


def require_history_access() -> None:
    raise AccessDenied("generation_history_connector_disabled")
