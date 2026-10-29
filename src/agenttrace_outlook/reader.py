"""Exact-mailbox read adapter reusing certificate auth and the bounded Microsoft transport."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from agenttrace_foundation.authorization import AccessDenied
from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.contracts import IngestionError
from agenttrace_ingestion.transport import MicrosoftTransport

from .config import RuntimeConfig
from .errors import OutlookError, SourceError

DELTA_FIELDS = "id,changeKey,parentFolderId,receivedDateTime,isDraft,categories"
FOLDER_FIELDS = "id,parentFolderId,childFolderCount,isHidden"
DETAIL_FIELDS = "id,changeKey,parentFolderId,receivedDateTime,sentDateTime,isDraft,internetMessageId,internetMessageHeaders,categories,subject"


class ReadTransport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str]) -> dict[str, Any]: ...


class MailReader:
    def __init__(self, config: RuntimeConfig, transport: ReadTransport):
        self._transport = transport
        self._base = "https://graph.microsoft.com/v1.0/users/" + str(config.scope.mailbox_id)
        self.page_size = config.page_size

    def _get(self, url: str) -> dict[str, Any]:
        try:
            return self._transport.request(
                "GET",
                url,
                headers={"Prefer": f'IdType="ImmutableId", odata.maxpagesize={self.page_size}'},
            )
        except IngestionError as error:
            raise SourceError(
                error.code, retryable=error.retryable, retry_after=error.retry_after
            ) from None
        except AccessDenied:
            raise SourceError("source_authentication_unavailable") from None

    def well_known(self, name: str) -> dict[str, Any]:
        if name not in {"drafts", "sentitems", "outbox", "deleteditems"}:
            raise OutlookError("unsupported_system_folder")
        return self._get(self._base + "/mailFolders/" + name + "?$select=id")

    def collection_url(self, kind: str, target: str) -> str:
        if kind == "discover":
            path = (
                "/mailFolders"
                if target == "root"
                else "/mailFolders/" + quote(target, safe="") + "/childFolders"
            )
            query = {
                "$select": FOLDER_FIELDS,
                "$top": str(self.page_size),
                "includeHiddenFolders": "true",
            }
        elif kind == "delta":
            path = "/mailFolders/" + quote(target, safe="") + "/messages/delta"
            query = {"$select": DELTA_FIELDS, "$top": str(self.page_size)}
        else:
            raise OutlookError("unsupported_collection")
        return self._base + path + "?" + urlencode(query)

    def validate_cursor(self, url: str, kind: str, target: str) -> None:
        if not isinstance(url, str) or len(url) > 32768:
            raise SourceError("unsafe_source_cursor")
        parsed, initial = urlsplit(url), urlsplit(self.collection_url(kind, target))
        expected = unquote(initial.path)
        alternate = (
            expected.replace("/mailFolders/" + target, "/mailFolders('" + target + "')")
            if target != "root"
            else expected
        )
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.fragment
            or unquote(parsed.path) not in {expected, alternate}
        ):
            raise SourceError("unsafe_source_cursor")
        query = parse_qs(parsed.query, keep_blank_values=True)
        allowed = {"$skiptoken", "$deltatoken", "$select", "$top", "$skip", "includeHiddenFolders"}
        if (
            not query
            or set(query) - allowed
            or any(len(v) != 1 or not v[0] for v in query.values())
        ):
            raise SourceError("unsafe_source_cursor")
        if "$select" in query and query["$select"][0] != (
            FOLDER_FIELDS if kind == "discover" else DELTA_FIELDS
        ):
            raise SourceError("unsafe_source_cursor")
        for name in ("$top", "$skip"):
            if name in query and (
                not query[name][0].isdigit()
                or (name == "$top" and not 1 <= int(query[name][0]) <= self.page_size)
            ):
                raise SourceError("unsafe_source_cursor")
        if "includeHiddenFolders" in query and (
            kind != "discover" or query["includeHiddenFolders"] != ["true"]
        ):
            raise SourceError("unsafe_source_cursor")

    def page(self, kind: str, target: str, cursor: str | None) -> dict[str, Any]:
        url = cursor or self.collection_url(kind, target)
        self.validate_cursor(url, kind, target)
        return self._get(url)

    def sync_detail(self, message_id: str, *, include_headers: bool = True) -> dict[str, Any]:
        if not 1 <= len(message_id) <= 2048:
            raise OutlookError("invalid_message_reference")
        return self._get(
            self._base
            + "/messages/"
            + quote(message_id, safe="")
            + "?"
            + urlencode(
                {
                    "$select": DETAIL_FIELDS
                    if include_headers
                    else "id,changeKey,parentFolderId,receivedDateTime,isDraft,subject"
                }
            )
        )

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
