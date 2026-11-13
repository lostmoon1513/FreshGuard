"""One error format for the whole API: {"error": {"code": ..., "message": ...}}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def error_body(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


_CODES = {
    401: "unauthorized",
    404: "not_found",
    405: "method_not_allowed",
    422: "validation_error",
    429: "rate_limited",
}


def code_for_status(status: int) -> str:
    return _CODES.get(status, "internal_error" if status >= 500 else "bad_request")


def validation_message(errors: list[dict[str, Any]]) -> str:
    """Short, safe summary of pydantic/FastAPI validation errors (no input values echoed)."""
    parts = []
    for err in errors[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body", "query"))
        parts.append(
            f"{loc}: {err.get('msg', 'invalid')}" if loc else str(err.get("msg", "invalid"))
        )
    return "; ".join(parts) or "Invalid request."