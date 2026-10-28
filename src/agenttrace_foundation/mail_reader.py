"""Allowlisted Graph GET adapter; no generic request, pagination or mutation method."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .access_policy import EvidenceCapability, MailboxReadPolicy, require_allowed_egress
from .authorization import AccessDenied, audit


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


@dataclass(frozen=True)
class AuthorizedBody:
    """Private transient value. Neither repr nor routine audit output contains the body."""

    capability: EvidenceCapability
    content_type: str
    text: str = field(repr=False)


class ReadOnlyMailReader:
    def __init__(self, policy: MailboxReadPolicy, token: Callable[[], str]):
        self.policy = policy
        self._token = token

    def read_body(self, capability: EvidenceCapability) -> AuthorizedBody:
        self.policy.authorize(capability)
        path = "/users/" + quote(capability.mailbox, safe="")
        path += "/messages/" + quote(capability.message_id, safe="")
        uri = (
            "https://graph.microsoft.com/v1.0"
            + path
            + "?"
            + urlencode({"$select": "id,body,changeKey,subject"})
        )
        require_allowed_egress(uri, component="mail_collector")
        request = Request(
            uri,
            headers={"Authorization": "Bearer " + self._token()},
            method="GET",
        )
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                source = response.read(262_145)
            if len(source) > 262_144:
                raise AccessDenied("message_body_too_large")
            value = json.loads(source)
            if value["id"] != capability.message_id or value["changeKey"] != capability.version:
                raise AccessDenied("message_version_changed")
            if not value["subject"].startswith("AgentTrace synthetic test:"):
                raise AccessDenied("synthetic_message_required")
            text = value["body"]["content"]
            if not isinstance(text, str):
                raise AccessDenied("invalid_message_body")
            audit("mailbox_read", "allowed")
            return AuthorizedBody(capability, value["body"]["contentType"], text)
        except HTTPError:
            audit("mailbox_read", "denied")
            raise AccessDenied("mailbox_source_unavailable_or_denied") from None
        except Exception:
            raise AccessDenied("mailbox_read_failed") from None
