"""Exact-mailbox read adapter reusing certificate auth and the bounded Microsoft transport."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlencode

from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.transport import MicrosoftTransport

from .config import RuntimeConfig
from .errors import OutlookError


class ReadTransport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str]) -> dict[str, Any]: ...


class MailReader:
    def __init__(self, config: RuntimeConfig, transport: ReadTransport):
        self._transport = transport
        self._base = "https://graph.microsoft.com/v1.0/users/" + str(config.scope.mailbox_id)

    def message_metadata(self, message_id: str) -> dict[str, Any]:
        if not 1 <= len(message_id) <= 2048:
            raise OutlookError("invalid_message_reference")
        # Callers cannot choose URLs, methods, expansions or body fields.
        query = urlencode(
            {
                "$select": "id,changeKey,parentFolderId,receivedDateTime,isDraft,internetMessageId,internetMessageHeaders,categories"
            }
        )
        return self._transport.request(
            "GET",
            self._base + "/messages/" + quote(message_id, safe="") + "?" + query,
            headers={"Prefer": 'IdType="ImmutableId"'},
        )


def certificate_reader(config: RuntimeConfig) -> MailReader:
    if config.reader_identity is None:
        raise OutlookError("reader_identity_not_configured")
    provider = CertificateTokenProvider(
        str(config.scope.tenant_id),
        str(config.reader_identity.client_id),
        config.reader_identity.certificate_thumbprint,
        Path(__file__).resolve().parents[2] / "scripts/manage-workload-certificate.ps1",
    )
    transport = MicrosoftTransport(
        lambda *, force_refresh=False: provider.token(
            "https://graph.microsoft.com", force_refresh=force_refresh
        )
    )
    return MailReader(config, transport)
