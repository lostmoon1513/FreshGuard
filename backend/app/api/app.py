"""FastAPI application factory. Routes are thin: validation, auth, then the service."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dashboard import DASHBOARD_HTML
from app.api.errors import ApiError, code_for_status, error_body, validation_message
from app.api.ratelimit import RateLimiter
from app.api.security import key_is_valid
from app.config import Settings
from app.db.store import VerificationRecord
from app.logging import new_request_id, set_request_id
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationRequest, VerificationResult
from app.services.verification_service import VerificationService

log = logging.getLogger(__name__)
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DONE = (VerificationStatus.COMPLETED, VerificationStatus.FAILED)


def _dump(result: VerificationResult) -> dict[str, Any]:
    return result.model_dump(mode="json")


def _dump_record(record: VerificationRecord) -> dict[str, Any]:
    """Result plus what was asked, so a UI can show the question and answer."""
    out = _dump(record.result)
    out["question"] = record.request.question
    out["answer"] = record.request.answer
    out["answer_generated_at"] = (
        record.request.answer_generated_at.isoformat()
        if record.request.answer_generated_at
        else None
    )
    return out


def create_app(service: VerificationService, settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await service.recover()
        yield
        await service.shutdown()

    app = FastAPI(title="FreshGuard", version="1.0.0", lifespan=lifespan)
    limiter = RateLimiter(settings.rate_limit_per_minute)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST"],
            allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied = request.headers.get("x-request-id", "")
        rid = supplied if _REQUEST_ID.match(supplied) else new_request_id()
        set_request_id(rid)
        try:
            response = await call_next(request)
        except Exception:
            log.exception("Unhandled error")
            response = JSONResponse(
                error_body("internal_error", "Internal server error."), status_code=500
            )
        response.headers["X-Request-ID"] = rid
        return response

    # ---- error handlers --------------------------------------------------------------------
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            error_body(exc.code, exc.message), status_code=exc.status, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        message = validation_message(list(exc.errors()))
        return JSONResponse(error_body("validation_error", message), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return JSONResponse(
            error_body(code_for_status(exc.status_code), message),
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error")
        return JSONResponse(error_body("internal_error", "Internal server error."), status_code=500)

    # ---- dependencies ----------------------------------------------------------------------
    async def require_key(x_api_key: str | None = Header(default=None)) -> str:
        if not key_is_valid(settings.freshguard_api_key, x_api_key):
            raise ApiError(401, "unauthorized", "Missing or invalid API key.")
        return x_api_key or "anonymous"

    async def throttle(request: Request, caller: str = Depends(require_key)) -> None:
        client = request.client.host if request.client else "unknown"
        wait = limiter.check(f"{caller}:{client}")
        if wait is not None:
            raise ApiError(
                429, "rate_limited", "Too many requests.", headers={"Retry-After": str(wait)}
            )

    # ---- routes ----------------------------------------------------------------------------
    @app.get("/dashboard", include_in_schema=False)
    async def dashboard() -> HTMLResponse:
        # The page holds no secrets: it asks for the API key and sends it with each call.
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_key)])

    async def respond(
        pending: VerificationResult, response: Response, wait: bool, timeout: int
    ) -> dict[str, Any]:
        if not wait:
            return {"id": pending.id, "status": pending.status.value}
        result = await service.wait(pending.id, timeout=timeout)
        if result is None:  # cannot happen: we just created it
            raise ApiError(500, "internal_error", "Internal server error.")
        if result.status in _DONE:
            response.status_code = 200
            return _dump(result)
        return {"id": result.id, "status": result.status.value}

    @v1.post("/verifications", status_code=202, dependencies=[Depends(throttle)])
    async def submit(
        body: VerificationRequest,
        response: Response,
        wait: bool = False,
        timeout: int = Query(default=60, ge=1, le=120),
    ) -> dict[str, Any]:
        return await respond(await service.submit(body), response, wait, timeout)

    @v1.post(
        "/verifications/{verification_id}/reverify",
        status_code=202,
        dependencies=[Depends(throttle)],
    )
    async def reverify(
        verification_id: str,
        response: Response,
        wait: bool = False,
        timeout: int = Query(default=60, ge=1, le=120),
    ) -> dict[str, Any]:
        pending = await service.reverify(verification_id)
        if pending is None:
            raise ApiError(404, "not_found", "Verification not found.")
        return await respond(pending, response, wait, timeout)

    @v1.get("/verifications/{verification_id}")
    async def fetch(verification_id: str) -> dict[str, Any]:
        record = await service.get_record(verification_id)
        if record is None:
            raise ApiError(404, "not_found", "Verification not found.")
        return _dump_record(record)

    @v1.get("/verifications")
    async def list_verifications(
        limit: int = Query(default=20, ge=1, le=100),
        label: Label | None = None,
        before: str | None = Query(default=None, max_length=64),
    ) -> dict[str, Any]:
        items, next_before = await service.list_records(limit=limit, label=label, before=before)
        return {"items": [_dump_record(r) for r in items], "next_before": next_before}

    app.include_router(v1)
    return app