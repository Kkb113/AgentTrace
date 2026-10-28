"""Narrow notification receiver and authenticated ingestion health; no email writes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agenttrace_foundation.authorization import AccessDenied, AuthorizationPolicy, TokenValidator
from agenttrace_foundation.database import StorageUnavailable

from .contracts import IngestionError
from .notifications import NotificationValidator
from .store import IngestionStore


def create_app(
    store: IngestionStore,
    notifications: NotificationValidator,
    *,
    policy: AuthorizationPolicy | None = None,
    validator: TokenValidator | None = None,
) -> FastAPI:
    app = FastAPI(title="AgentTrace read-only ingestion", version="0.4.0")

    @app.post("/v1/notifications")
    async def notify(request: Request) -> PlainTextResponse:
        challenge = request.query_params.get("validationToken")
        if challenge is not None:
            if not 1 <= len(challenge) <= 1024 or any(ord(c) < 32 for c in challenge):
                raise HTTPException(400, "invalid_validation_challenge")
            return PlainTextResponse(challenge, status_code=200)
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 65_536:
                raise HTTPException(413, "notification_size_limit")
        try:
            items = notifications.parse(bytes(chunks))
            store.accept(items)  # Commit must complete before acknowledging the batch.
        except IngestionError as error:
            raise HTTPException(400, error.code) from None
        except StorageUnavailable:
            raise HTTPException(503, "notification_store_unavailable") from None
        return PlainTextResponse("accepted", status_code=202)

    @app.get("/v1/ingestion/sources/{source_ref}")
    def health(
        source_ref: UUID, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, object]:
        if (
            policy is None
            or validator is None
            or authorization is None
            or not authorization.startswith("Bearer ")
        ):
            raise HTTPException(401, "valid_api_access_token_required")
        try:
            principal = validator.validate(authorization[7:])
            # A server-owned source reference is bound to its enrolled mailbox in the
            # same entitlement map used by decisions; client parameters cannot add it.
            policy.authorize(principal, str(source_ref))
        except AccessDenied:
            raise HTTPException(404, "source_not_found") from None
        try:
            return store.health(source_ref)
        except IngestionError:
            raise HTTPException(404, "source_not_found") from None
        except StorageUnavailable:
            raise HTTPException(503, "ingestion_health_unavailable") from None

    return app
