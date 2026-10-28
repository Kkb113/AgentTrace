"""Fail-closed access-token validation and server-owned message entitlements."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.request import Request, urlopen
from uuid import UUID

import jwt
from jwt import PyJWK

ROLES = frozenset({"Detection.Viewer", "Detection.Investigator", "Detection.Administrator"})
LOGGER = logging.getLogger("agenttrace.security")


def configure_security_logging() -> None:
    LOGGER.setLevel(logging.INFO)
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


class AccessDenied(ValueError):
    """A safe error code, never the token or upstream response."""


def audit(event: str, outcome: str, subject: str = "") -> None:
    LOGGER.info(
        json.dumps(
            {
                "event": event,
                "outcome": outcome,
                "subject_ref": hashlib.sha256(subject.encode()).hexdigest()[:20]
                if subject
                else None,
            },
            separators=(",", ":"),
        )
    )


@dataclass(frozen=True)
class Principal:
    tenant: str
    subject: str
    client: str
    roles: frozenset[str]
    application: bool


class TokenValidator(Protocol):
    def validate(self, token: str) -> Principal: ...


@dataclass(frozen=True)
class AuthorizationPolicy:
    tenant: str
    audience: str
    allowed_clients: frozenset[str]
    # Subject -> explicitly enrolled mailboxes. No implicit administrator bypass.
    subjects: Mapping[str, frozenset[str]] = field(repr=False)
    # Message reference -> owning mailbox, established server-side at enrollment/ingestion.
    messages: Mapping[str, str] = field(repr=False)
    local_jwks_file: Path | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        UUID(self.tenant)
        UUID(self.audience)
        if not self.allowed_clients:
            raise ValueError("explicit_api_clients_required")
        for value in self.allowed_clients:
            UUID(value)
        for subject, mailboxes in self.subjects.items():
            UUID(subject)
            if not mailboxes:
                raise ValueError("empty_subject_entitlement")

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant}/v2.0"

    def authorize(self, principal: Principal, message_ref: str) -> None:
        mailbox = self.messages.get(message_ref)
        if (
            principal.tenant != self.tenant
            or not principal.roles.intersection(ROLES)
            or mailbox is None
            or mailbox not in self.subjects.get(principal.subject, frozenset())
        ):
            audit("decision_access", "denied", principal.subject)
            raise AccessDenied("message_access_denied")
        audit("decision_access", "allowed", principal.subject)

    @classmethod
    def load(cls, path: Path, *, local_synthetic: bool) -> AuthorizationPolicy:
        data = json.loads(path.read_text(encoding="utf-8"))
        local = data.get("local_jwks_file")
        if local and not local_synthetic:
            raise ValueError("local_signing_keys_forbidden_outside_synthetic_environment")
        return cls(
            tenant=data["tenant"],
            audience=data["audience"],
            allowed_clients=frozenset(data["allowed_clients"]),
            subjects={key: frozenset(value) for key, value in data["subjects"].items()},
            messages=data["messages"],
            local_jwks_file=Path(local) if local else None,
        )


class EntraKeySet:
    """Fetch keys from the configured tenant only; never follow token-supplied URLs."""

    def __init__(self, policy: AuthorizationPolicy):
        self.policy = policy
        self.keys: dict[str, Any] = {}
        self.refreshed_at = 0.0
        self.last_attempt = 0.0
        self.lock = threading.Lock()

    def __call__(self, key_id: str) -> Any:
        with self.lock:
            now = time.monotonic()
            if not self.keys or now - self.refreshed_at > 3600 or key_id not in self.keys:
                if self.last_attempt and now - self.last_attempt < 30:
                    raise AccessDenied("signing_key_unavailable")
                self.last_attempt = now
                try:
                    if self.policy.local_jwks_file:
                        source = self.policy.local_jwks_file.read_bytes()
                    else:
                        uri = f"https://login.microsoftonline.com/{self.policy.tenant}/discovery/v2.0/keys"
                        with urlopen(Request(uri, method="GET"), timeout=10) as response:
                            if response.url != uri:
                                raise AccessDenied("unexpected_signing_key_redirect")
                            source = response.read(262_145)
                    if len(source) > 262_144:
                        raise AccessDenied("invalid_signing_key_set")
                    document = json.loads(source)
                    keys = {}
                    for entry in document["keys"]:
                        if entry.get("kty") != "RSA" or entry.get("use", "sig") != "sig":
                            continue
                        if entry.get("alg", "RS256") != "RS256":
                            continue
                        key = PyJWK.from_dict(entry, algorithm="RS256").key
                        if key.key_size < 2048:
                            raise AccessDenied("weak_signing_key")
                        # Entra shared key sets may include an issuer template.
                        key_issuer = entry.get("issuer", self.policy.issuer).replace(
                            "{tenantid}", self.policy.tenant
                        )
                        if key_issuer != self.policy.issuer:
                            continue
                        keys[entry["kid"]] = key
                    self.keys = keys
                    self.refreshed_at = now
                except Exception:
                    raise AccessDenied("signing_key_unavailable") from None
            if key_id not in self.keys:
                raise AccessDenied("untrusted_signing_key")
            return self.keys[key_id]


class EntraTokenValidator:
    def __init__(
        self, policy: AuthorizationPolicy, key_resolver: Callable[[str], Any] | None = None
    ):
        self.policy = policy
        self.key_resolver = key_resolver or EntraKeySet(policy)

    def validate(self, token: str) -> Principal:
        try:
            if not 32 <= len(token) <= 16_384:
                raise AccessDenied("invalid_access_token")
            header = jwt.get_unverified_header(token)
            if (
                header.get("alg") != "RS256"
                or header.get("typ") not in {"JWT", "at+jwt"}
                or not isinstance(header.get("kid"), str)
                or not 1 <= len(header["kid"]) <= 128
                or any(name in header for name in ("jku", "x5u", "crit"))
            ):
                raise AccessDenied("invalid_access_token")
            claims = jwt.decode(
                token,
                self.key_resolver(header["kid"]),
                algorithms=["RS256"],
                audience=self.policy.audience,
                issuer=self.policy.issuer,
                options={
                    "require": ["exp", "nbf", "iat", "iss", "aud", "tid", "oid", "azp", "ver"],
                    "strict_aud": True,
                },
            )
            if claims["tid"] != self.policy.tenant or claims["ver"] != "2.0":
                raise AccessDenied("invalid_access_token")
            if claims["azp"] not in self.policy.allowed_clients:
                raise AccessDenied("unapproved_api_client")
            UUID(claims["oid"])
            roles = claims.get("roles")
            if (
                not isinstance(roles, list)
                or not roles
                or not all(isinstance(x, str) for x in roles)
            ):
                raise AccessDenied("api_role_required")
            application = claims.get("idtyp") == "app"
            if application:
                # A machine may view its enrolled fixtures; human administrative roles stay human.
                if set(roles) != {"Detection.Viewer"} or "scp" in claims:
                    raise AccessDenied("application_role_not_allowed")
            elif "Detection.Read" not in claims.get("scp", "").split():
                # ID tokens carry no delegated API scope and cannot be substituted.
                raise AccessDenied("api_access_scope_required")
            principal = Principal(
                claims["tid"], claims["oid"], claims["azp"], frozenset(roles), application
            )
            if not principal.roles.intersection(ROLES):
                raise AccessDenied("api_role_required")
            audit("token_validation", "allowed", principal.subject)
            return principal
        except Exception:
            audit("token_validation", "denied")
            raise AccessDenied("invalid_access_token") from None
