"""Evidence submission and bounded correlation/history queries; no execution endpoints."""

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from agenttrace_foundation.authorization import (
    AccessDenied,
    AuthorizationPolicy,
    Principal,
    TokenValidator,
    audit,
)
from agenttrace_foundation.database import StorageUnavailable
from agenttrace_ingestion.contracts import IngestionError

from .canonical import LedgerError, strict_json
from .contracts import CorrelationView, SignedEvidence
from .store import EvidenceLedger


class EvidenceAPI(FastAPI):
    def openapi(self) -> dict[str, Any]:
        if self.openapi_schema is None:
            specification = get_openapi(title=self.title, version=self.version, routes=self.routes)
            envelope = SignedEvidence.model_json_schema(ref_template="#/components/schemas/{model}")
            schemas = specification.setdefault("components", {}).setdefault("schemas", {})
            schemas.update(envelope.pop("$defs", {}))
            schemas["SignedEvidence"] = envelope
            self.openapi_schema = specification
        return self.openapi_schema


def create_app(
    ledger: EvidenceLedger,
    *,
    policy: AuthorizationPolicy | None = None,
    validator: TokenValidator | None = None,
) -> FastAPI:
    app = EvidenceAPI(title="AgentTrace evidence ledger", version="1.0")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": "invalid_evidence_request"})

    @app.exception_handler(StorageUnavailable)
    async def unavailable(request: Request, error: StorageUnavailable) -> JSONResponse:
        audit("ledger_storage", "unavailable")
        return JSONResponse(status_code=503, content={"detail": "evidence_store_unavailable"})

    @app.exception_handler(OSError)
    async def credential_file_unavailable(request: Request, error: OSError) -> JSONResponse:
        audit("ledger_storage", "unavailable")
        return JSONResponse(status_code=503, content={"detail": "evidence_store_unavailable"})

    @app.exception_handler(IngestionError)
    async def corrupt_storage(request: Request, error: IngestionError) -> JSONResponse:
        audit("ledger_integrity", "denied")
        return JSONResponse(status_code=503, content={"detail": "evidence_integrity_unavailable"})

    def authenticate(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not policy or not validator or not authorization:
            raise HTTPException(401, "valid_api_access_token_required")
        parts = authorization.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise HTTPException(401, "valid_api_access_token_required")
        try:
            return validator.validate(parts[1])
        except AccessDenied:
            raise HTTPException(401, "invalid_api_access_token") from None

    def scope(principal: Principal, message_ref: UUID) -> tuple[UUID, UUID]:
        try:
            if policy is None:
                raise AccessDenied("authorization_required")
            policy.authorize(principal, str(message_ref))
            return UUID(principal.tenant), UUID(policy.messages[str(message_ref)])
        except (AccessDenied, ValueError, KeyError):
            raise HTTPException(404, "evidence_not_found") from None

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        configured = policy is not None and validator is not None
        try:
            with ledger.database.connect() as connection:
                row = connection.execute("SELECT version FROM ledger_schema").fetchone()
            available = bool(row and row["version"] == 1)
        except (StorageUnavailable, OSError, ValueError):
            available = False
        return JSONResponse(
            status_code=200 if configured and available else 503,
            content={
                "status": "ready" if configured and available else "unavailable",
                "schema_version": "1.0",
                "authorization_configured": configured,
                "database_ready": available,
            },
        )

    @app.post(
        "/v1/evidence/receipts",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/SignedEvidence"}}
                },
            }
        },
    )
    async def submit(
        request: Request, principal: Annotated[Principal, Depends(authenticate)]
    ) -> dict[str, Any]:
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536:
                raise HTTPException(413, "evidence_size_limit")
        try:
            envelope = SignedEvidence.model_validate_json(json.dumps(strict_json(bytes(raw))))
        except (ValidationError, LedgerError, ValueError, TypeError):
            raise HTTPException(422, "invalid_signed_evidence") from None
        tenant, mailbox = scope(principal, envelope.record.message_ref)
        if tenant != envelope.record.tenant_id or mailbox != envelope.record.mailbox_id:
            raise HTTPException(404, "evidence_not_found")
        try:
            return ledger.submit(envelope, principal)
        except LedgerError as error:
            # Do not reveal issuer enrollment, key existence or raw identifiers.
            audit("ledger_evidence_submission", "denied", principal.subject)
            if str(error) == "evidence_event_reuse_conflict":
                raise HTTPException(409, "evidence_event_reuse_conflict") from None
            raise HTTPException(403, "evidence_not_accepted") from None

    @app.get(
        "/v1/evidence/messages/{message_ref}/versions/{version_ref}", response_model=CorrelationView
    )
    def view(
        message_ref: UUID, version_ref: UUID, principal: Annotated[Principal, Depends(authenticate)]
    ) -> CorrelationView:
        tenant, mailbox = scope(principal, message_ref)
        try:
            return CorrelationView.model_validate_json(
                json.dumps(ledger.view(tenant, mailbox, message_ref, version_ref))
            )
        except LedgerError as error:
            if str(error) == "ledger_message_not_found":
                raise HTTPException(404, "evidence_not_found") from None
            if str(error) == "evidence_view_limit_requires_bounded_export":
                raise HTTPException(409, "evidence_view_limit_requires_bounded_export") from None
            raise HTTPException(503, "evidence_integrity_unavailable") from None

    @app.post("/v1/evidence/messages/{message_ref}/versions/{version_ref}/inputs")
    def record_inputs(
        message_ref: UUID, version_ref: UUID, principal: Annotated[Principal, Depends(authenticate)]
    ) -> dict[str, str]:
        tenant, mailbox = scope(principal, message_ref)
        if not principal.roles.intersection({"Detection.Investigator", "Detection.Administrator"}):
            raise HTTPException(403, "investigator_role_required")
        try:
            ref = ledger.record_inputs(tenant, mailbox, message_ref, version_ref)
        except LedgerError:
            raise HTTPException(404, "evidence_not_found") from None
        audit("ledger_input_snapshot", "allowed", principal.subject)
        return {"input_ref": str(ref), "schema_version": "1.0"}

    @app.get("/v1/evidence/messages/{message_ref}/history")
    def history(
        message_ref: UUID, principal: Annotated[Principal, Depends(authenticate)]
    ) -> dict[str, Any]:
        tenant, mailbox = scope(principal, message_ref)
        try:
            return {
                "schema_version": "1.0",
                "history": ledger.history(tenant, mailbox, message_ref),
                "current_trust_must_be_reassessed": True,
            }
        except LedgerError:
            raise HTTPException(409, "evidence_history_unavailable") from None

    return app
