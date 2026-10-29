"""Scope and minimization rules shared by Graph logging setup and collection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from .contracts import IngestionError


@dataclass(frozen=True)
class ActivityScope:
    tenant: UUID
    pilot_user: UUID
    clients: frozenset[UUID]
    collectors: frozenset[UUID]

    def __post_init__(self) -> None:
        if not self.clients or not self.collectors or not self.collectors.issubset(self.clients):
            raise ValueError("explicit_graph_activity_scope_required")

    def transform(self) -> str:
        clients = ",".join("'" + str(v) + "'" for v in sorted(self.clients, key=str))
        collectors = ",".join("'" + str(v) + "'" for v in sorted(self.collectors, key=str))
        # Source export is tenant-wide; the workspace transformation discards
        # unrelated rows before storage. This is minimization, not source OAuth scope.
        return (
            "source | where AadTenantId == '"
            + str(self.tenant)
            + "' | where AppId in ("
            + clients
            + ") | where UserId == '"
            + str(self.pilot_user)
            + "' or AppId in ("
            + collectors
            + ") | extend RequestUri=tostring(split(RequestUri, '?')[0]) | project TimeGenerated, AadTenantId, AppId, UserId, RequestId, ClientRequestId, RequestMethod, RequestUri, ResponseStatusCode"
        )


def minimal_request_uri(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "graph.microsoft.com"
        or parsed.username
        or parsed.password
    ):
        raise IngestionError("graph_activity_request_uri_out_of_scope")
    if len(parsed.path) > 8192:
        raise IngestionError("graph_activity_request_uri_size_limit")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def send_request_observed(method: str, uri: str, status: int) -> bool:
    path = urlsplit(minimal_request_uri(uri)).path
    return (
        method == "POST"
        and 200 <= status < 300
        and re.fullmatch(
            r"/(?:v1\.0|beta)/(?:me|users/[^/]+)/(?:sendMail|messages/[^/]+/(?:send|reply|replyAll|forward))/?",
            path,
            re.IGNORECASE,
        )
        is not None
    )
