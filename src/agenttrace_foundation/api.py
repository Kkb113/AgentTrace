"""Loopback-only foundation API: health and synthetic decision queries."""

from __future__ import annotations

from uuid import UUID

from agenttrace_contracts import DetectionDecision
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from .database import Database, StorageUnavailable
from .settings import Settings
from .store import DecisionStore


def create_app(database: Database | None = None) -> FastAPI:
    database = database or Database(Settings.from_environment())
    store = DecisionStore(database)
    app = FastAPI(title="AgentTrace local synthetic foundation", version="0.2.0")

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
            }
        except (StorageUnavailable, OSError, ValueError):
            checks = {"database": False, "attribution_worker": False, "content_worker": False}
        return JSONResponse(
            status_code=200 if all(checks.values()) else 503,
            content={
                "status": "ready" if all(checks.values()) else "unavailable",
                "checks": checks,
                "content_model": "not_installed",
                "external_mail_access": "not_configured",
            },
        )

    @app.get("/v1/decisions/{decision_id}", response_model=DetectionDecision)
    def decision(decision_id: UUID) -> DetectionDecision:
        try:
            result = store.get(decision_id)
        except (StorageUnavailable, OSError, ValueError) as exc:
            raise HTTPException(503, "decision_store_unavailable") from exc
        if result is None:
            raise HTTPException(404, "decision_not_found")
        return result

    return app
