"""Explicit operator enrollment of agent send applications, never display-name discovery."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from .contracts import Code, Record


class AgentProvider(Record):
    provider_key: Code
    client_id: UUID
    publisher_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    publisher_owner_tenant: UUID
    send_evidence: Literal["exchange_send"] = "exchange_send"
    declaration: Literal["mcp_office365", "authenticated_application"]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()

    @property
    def evidence_ref(self) -> str:
        return "provider-sha256:" + self.fingerprint


def declaration_matches(provider: AgentProvider | None, declarations: list[str]) -> bool:
    # Headerless routes need independently authenticated application execution.
    # A conflicting/unknown declaration must not be hidden by that evidence.
    if provider is None or provider.declaration == "mcp_office365":
        return declarations == ["mcp-office365"]
    return not declarations


def provider_for_send(
    records: list[dict[str, Any]], message_id: str, providers: tuple[AgentProvider, ...]
) -> AgentProvider | None:
    actors = set()
    for row in records:
        data = row.get("auditData")
        if not isinstance(data, dict) or not isinstance(data.get("Item"), dict):
            return None
        if data["Item"].get("InternetMessageId") == message_id:
            actor = data.get("ClientAppId")
            if not isinstance(actor, str):
                return None
            actors.add(actor)
    return next((p for p in providers if actors == {str(p.client_id)}), None)
