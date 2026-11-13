"""Shared, I/O-free logic for the sync and async clients: request building, response parsing,
error mapping, retry timing. Easy to test without a network."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from freshguard.errors import (
    AuthError,
    FreshGuardError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from freshguard.models import Verification

MAX_SERVER_WAIT = 120  # the API caps ?wait=true&timeout= at this many seconds
DEFAULT_POLL_INTERVAL = 2.0


@dataclass(frozen=True)
class Response:
    status: int
    body: Any  # parsed JSON, or None if the body was not JSON
    headers: dict[str, str] = field(default_factory=dict)  # lower-case names


class Transport(Protocol):
    """Sync transport. Raises `ConnectionFailed` on network errors and timeouts."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float,
    ) -> Response: ...

    def close(self) -> None: ...


class AsyncTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float,
    ) -> Response: ...

    async def aclose(self) -> None: ...


def build_headers(api_key: str | None) -> dict[str, str]:
    headers = {"accept": "application/json", "user-agent": "freshguard-python/0.1"}
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def submit_body(
    question: str,
    answer: str,
    answer_generated_at: Any = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the obvious mistakes locally and build the JSON body."""
    if not isinstance(question, str) or not question.strip():
        raise ValidationError("question must be a non-empty string.")
    if not isinstance(answer, str) or not answer.strip():
        raise ValidationError("answer must be a non-empty string.")
    body: dict[str, Any] = {"question": question, "answer": answer}
    if answer_generated_at is not None:
        stamp = answer_generated_at
        body["answer_generated_at"] = stamp.isoformat() if hasattr(stamp, "isoformat") else stamp
    if metadata:
        body["metadata"] = {str(k): str(v) for k, v in metadata.items()}
    return body


def raise_for_response(response: Response) -> None:
    """Map a non-2xx response to the right exception. Does nothing for 2xx."""
    if 200 <= response.status < 300:
        return
    request_id = response.headers.get("x-request-id")
    code = message = None
    if isinstance(response.body, dict) and isinstance(response.body.get("error"), dict):
        code = response.body["error"].get("code")
        message = response.body["error"].get("message")
    message = message or f"HTTP {response.status}"
    extra = {"status": response.status, "code": code, "request_id": request_id}
    if response.status == 401:
        raise AuthError(message, **extra)
    if response.status == 404:
        raise NotFoundError(message, **extra)
    if response.status == 422:
        raise ValidationError(message, **extra)
    if response.status == 429:
        raise RateLimitError(message, retry_after=_retry_after(response), **extra)
    if response.status >= 500:
        raise ServerError(message, **extra)
    raise FreshGuardError(message, **extra)


def _retry_after(response: Response) -> float | None:
    try:
        return float(response.headers.get("retry-after", ""))
    except ValueError:
        return None


def expect_json(response: Response) -> dict[str, Any]:
    if not isinstance(response.body, dict):
        raise ServerError(
            "The server returned something that is not FreshGuard JSON.",
            status=response.status,
            request_id=response.headers.get("x-request-id"),
        )
    return response.body


def parse_verification(response: Response) -> Verification:
    data = expect_json(response)
    if "id" not in data:
        raise ServerError("Response has no 'id'.", status=response.status)
    return Verification.from_dict(data)


def should_retry(response: Response) -> bool:
    return response.status >= 500


def backoff_seconds(attempt: int) -> float:
    """0.5s, 1s, 2s ... for retry number `attempt` (0-based)."""
    return 0.5 * (2**attempt)


def list_params(limit: int, label: str | None, before: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if label:
        params["label"] = label
    if before:
        params["before"] = before
    return params