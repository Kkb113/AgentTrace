"""Isolated certificate audit reader. POST creates a bounded analytical search, never mail."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from agenttrace_feasibility.capabilities import azure_cli_prefix
from agenttrace_foundation.authorization import AccessDenied
from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.contracts import IngestionError
from agenttrace_ingestion.transport import MicrosoftTransport

from .config import RuntimeConfig
from .errors import OutlookError, SourceError
from .sender_rules import CLAUDE_APP

ROOT = "https://graph.microsoft.com/v1.0/security/auditLog/queries"


class AuditReader:
    def __init__(self, config: RuntimeConfig, transport: Any):
        if config.sender_source is None:
            raise OutlookError("sender_source_not_configured")
        self.config, self.transport = config, transport

    def create(self, sent_at: datetime) -> str:
        source = self.config.sender_source
        assert source is not None
        try:
            result = self.transport.request(
                "POST",
                ROOT,
                body={
                    "displayName": "AgentTrace scoped synthetic sender evidence",
                    "filterStartDateTime": (sent_at - timedelta(minutes=2)).isoformat(),
                    "filterEndDateTime": (sent_at + timedelta(minutes=2)).isoformat(),
                    "recordTypeFilters": ["exchangeItem"],
                    "operationFilters": ["Send"],
                    "userPrincipalNameFilters": [source.mailbox_address],
                },
            )
            return str(UUID(result["id"]))
        except IngestionError as error:
            raise SourceError(
                error.code, retryable=error.retryable, retry_after=error.retry_after
            ) from None
        except AccessDenied:
            raise SourceError("source_authentication_unavailable") from None
        except (ValueError, KeyError, TypeError):
            raise SourceError("audit_query_identity_invalid") from None

    def query(self, query_id: str) -> dict[str, Any]:
        return self._get(ROOT + "/" + str(UUID(query_id)))

    def records(self, query_id: str, cursor: str | None) -> dict[str, Any]:
        path = ROOT + "/" + str(UUID(query_id)) + "/records"
        url = cursor or path + "?$top=100"
        self.validate_page(query_id, url)
        return self._get(url)

    @staticmethod
    def validate_page(query_id: str, url: str) -> None:
        base = urlsplit(ROOT + "/" + str(UUID(query_id)) + "/records")
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if (
            len(url) > 32768
            or parsed.scheme != "https"
            or parsed.netloc != base.netloc
            or parsed.path != base.path
            or parsed.fragment
            or set(query) - {"$top", "$skiptoken", "$skip"}
            or any(len(v) != 1 or not v[0] for v in query.values())
        ):
            raise SourceError("audit_page_out_of_scope")

    def _get(self, url: str) -> dict[str, Any]:
        try:
            result: dict[str, Any] = self.transport.request("GET", url)
            if not isinstance(result, dict):
                raise SourceError("audit_source_shape_invalid")
            return result
        except IngestionError as error:
            raise SourceError(
                error.code, retryable=error.retryable, retry_after=error.retry_after
            ) from None
        except AccessDenied:
            raise SourceError("source_authentication_unavailable") from None


def certificate_audit(config: RuntimeConfig) -> AuditReader:
    source = config.sender_source
    if source is None:
        raise OutlookError("sender_source_not_configured")
    identity = source.audit_identity
    provider = CertificateTokenProvider(
        str(config.scope.tenant_id),
        str(identity.client_id),
        identity.certificate_thumbprint,
        Path(__file__).resolve().parents[2] / "scripts/manage-workload-certificate.ps1",
    )
    return AuditReader(
        config,
        MicrosoftTransport(
            lambda *, force_refresh=False: provider.token(
                "https://graph.microsoft.com", force_refresh=force_refresh
            )
        ),
    )


def publisher_snapshot(config: RuntimeConfig) -> dict[str, Any]:
    """Read the exact enrolled SP with the existing interactive operator identity."""
    source = config.sender_source
    if source is None:
        raise SourceError("sender_source_not_configured")
    command = [
        *azure_cli_prefix(),
        "account",
        "show",
        "--subscription",
        str(source.subscription_id),
        "-o",
        "json",
        "--only-show-errors",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=30, shell=False, check=False)
        account = json.loads(result.stdout.decode("utf-8-sig"))
        if (
            result.returncode
            or not isinstance(account, dict)
            or account.get("tenantId") != str(config.scope.tenant_id)
        ):
            raise SourceError("publisher_operator_scope_mismatch")
        url = "https://graph.microsoft.com/v1.0/servicePrincipals?" + urlencode(
            {
                "$filter": "appId eq '" + CLAUDE_APP + "'",
                "$select": "appId,appOwnerOrganizationId,accountEnabled,verifiedPublisher",
            }
        )
        result = subprocess.run(
            [
                *azure_cli_prefix(),
                "rest",
                "--method",
                "GET",
                "--url",
                url,
                "--subscription",
                str(source.subscription_id),
                "-o",
                "json",
                "--only-show-errors",
            ],
            capture_output=True,
            timeout=30,
            shell=False,
            check=False,
        )
        if result.returncode or len(result.stdout) > 1048576:
            raise SourceError("publisher_registry_unavailable")
        data = json.loads(result.stdout.decode("utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("value"), list):
            raise SourceError("publisher_registry_shape_invalid")
        rows = data.get("value", [])
        if len(rows) != 1 or data.get("@odata.nextLink"):
            raise SourceError("publisher_registry_ambiguous")
        row = rows[0]
        if not isinstance(row, dict) or not isinstance(row.get("verifiedPublisher"), dict):
            raise SourceError("publisher_registry_shape_invalid")
        if (
            row.get("appId") != CLAUDE_APP
            or row.get("accountEnabled") is not True
            or row.get("appOwnerOrganizationId") != str(source.publisher_owner_tenant)
            or row.get("verifiedPublisher", {}).get("verifiedPublisherId") != source.publisher_id
        ):
            raise SourceError("publisher_pin_mismatch_or_revoked")
        answer: dict[str, Any] = row
        return answer
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise SourceError("publisher_registry_unavailable") from None
