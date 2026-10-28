"""Bounded Microsoft HTTPS transport with no redirects and credential-safe errors."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from agenttrace_foundation.mail_reader import NoRedirect

from .contracts import IngestionError


class TokenSource(Protocol):
    def __call__(self, *, force_refresh: bool = False) -> str: ...


def retry_after(value: str | None, *, now: datetime | None = None) -> int:
    try:
        if value is None:
            return 1
        seconds = (
            int(value)
            if value.strip().isdigit()
            else int((parsedate_to_datetime(value) - (now or datetime.now(UTC))).total_seconds())
        )
        return min(3600, max(1, seconds))
    except (ValueError, TypeError, OverflowError):
        return 1


class MicrosoftTransport:
    def __init__(
        self,
        token: TokenSource,
        *,
        host: str = "graph.microsoft.com",
        opener: Callable[..., Any] | None = None,
    ):
        if host not in {"graph.microsoft.com", "manage.office.com", "api.loganalytics.azure.com"}:
            raise ValueError("unsupported_microsoft_source_host")
        self._token, self.host = token, host
        self._open = opener or build_opener(NoRedirect()).open

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        maximum_bytes: int = 2_097_152,
    ) -> dict[str, Any]:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != self.host
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise IngestionError("source_url_out_of_scope")
        for attempt in range(2):
            try:
                request = Request(
                    url,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={
                        "Authorization": "Bearer " + self._token(force_refresh=attempt > 0),
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        **(headers or {}),
                    },
                    method=method,
                )
                with self._open(request, timeout=20) as response:
                    data = response.read(maximum_bytes + 1)
                    if len(data) > maximum_bytes:
                        raise IngestionError("source_response_size_limit")
                result: dict[str, Any] = json.loads(data) if data else {}
                if not isinstance(result, dict):
                    raise IngestionError("source_response_shape_invalid")
                return result
            except HTTPError as error:
                if error.code == 401 and attempt == 0:
                    continue
                if error.code in {408, 429, 500, 502, 503, 504}:
                    raise IngestionError(
                        "source_throttled"
                        if error.code == 429
                        else "source_temporarily_unavailable",
                        retryable=True,
                        retry_after=retry_after(error.headers.get("Retry-After")),
                    ) from None
                reasons = {
                    401: "source_authentication_expired",
                    403: "source_access_denied",
                    404: "source_item_not_found",
                    410: "source_cursor_expired",
                    412: "source_version_changed",
                    409: "source_subscription_conflict",
                }
                raise IngestionError(reasons.get(error.code, "source_request_rejected")) from None
            except (URLError, TimeoutError, OSError):
                raise IngestionError(
                    "source_network_unavailable", retryable=True, retry_after=2
                ) from None
            except (ValueError, UnicodeError):
                raise IngestionError("source_response_invalid") from None
        raise IngestionError("source_authentication_expired")
