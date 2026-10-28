"""Loopback-only foundation API: health and synthetic decision queries."""

import os
from pathlib import Path
from typing import Annotated
from uuid import UUID

from agenttrace_contracts import DetectionDecision
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from .authorization import (
    AccessDenied,
    AuthorizationPolicy,
    EntraTokenValidator,
    Principal,
    TokenValidator,
    audit,
    configure_security_logging,
)
from .database import Database, StorageUnavailable
from .settings import Settings
from .store import DecisionStore


def create_app(
    database: Database | None = None,
    *,
    policy: AuthorizationPolicy | None = None,
    validator: TokenValidator | None = None,
) -> FastAPI:
    configure_security_logging()
    database = database or Database(Settings.from_environment())
    store = DecisionStore(database)
    configured = os.environ.get("AGENTTRACE_AUTHORIZATION_FILE")
    if policy is None and configured:
        policy = AuthorizationPolicy.load(
            Path(configured),
            local_synthetic=os.environ.get("AGENTTRACE_ENVIRONMENT", "local_synthetic")
            == "local_synthetic",
        )
    validator = validator or (EntraTokenValidator(policy) if policy else None)
    app = FastAPI(title="AgentTrace synthetic detection sandbox", version="0.3.0")

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if validator is None or authorization is None:
            audit("token_validation", "denied")
            raise HTTPException(
                401, "valid_api_access_token_required", headers={"WWW-Authenticate": "Bearer"}
            )
        parts = authorization.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer":
            audit("token_validation", "denied")
            raise HTTPException(401, "valid_api_access_token_required")
        try:
            return validator.validate(parts[1])
        except AccessDenied:
            raise HTTPException(401, "invalid_api_access_token") from None

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive", "environment": "local_synthetic"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        try:
            checks = {
                "database": database.healthy(),
                "attribution_worker": store.role_healthy("attribution"),
                "content_worker": store.role_healthy("content"),
                "authorization": policy is not None and validator is not None,
            }
        except (StorageUnavailable, OSError, ValueError):
            checks = {
                "database": False,
                "attribution_worker": False,
                "content_worker": False,
                "authorization": policy is not None and validator is not None,
            }
        return JSONResponse(
            status_code=200 if all(checks.values()) else 503,
            content={
                "status": "ready" if all(checks.values()) else "unavailable",
                "checks": checks,
                "content_model": "not_installed",
                "external_mail_access": "not_configured",
                "authorization": "configured" if policy and validator else "deny_all",
            },
        )

    @app.get("/v1/decisions/{decision_id}", response_model=DetectionDecision)
    def decision(
        decision_id: UUID, principal: Annotated[Principal, Depends(authenticate)]
    ) -> DetectionDecision:
        try:
            result = store.get(decision_id)
        except (StorageUnavailable, OSError, ValueError) as exc:
            raise HTTPException(503, "decision_store_unavailable") from exc
        if result is None:
            raise HTTPException(404, "decision_not_found")
        try:
            if policy is None:
                raise AccessDenied("authorization_policy_required")
            policy.authorize(principal, result.message_ref)
        except AccessDenied:
            raise HTTPException(404, "decision_not_found") from None
        return result

    return app
