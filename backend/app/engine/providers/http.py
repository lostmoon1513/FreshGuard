"""A minimal async HTTP interface plus retry/error mapping shared by all real providers.

Why an interface: provider logic (request shape, response parsing, error mapping, retries) is
tested here with a scripted fake client, with no network. `httpx_client.py` is the one thin
adapter to the real `httpx`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.engine.providers.errors import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderUnavailable,
)

log = logging.getLogger(__name__)


class HttpTransportError(Exception):
    """Connection failure or timeout (no HTTP response was received)."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""
    headers: Mapping[str, str] = field(default_factory=dict)  # lower-cased names

    def json(self) -> Any:
        return json.loads(self.body)  # ValueError if not JSON


class HttpClient(Protocol):
    async def post_json(
        self, url: str, *, headers: Mapping[str, str], body: Any, timeout: float
    ) -> HttpResponse: ...


@dataclass(frozen=True)
class RetryPolicy:
    """Retry transient failures (network, 5xx, short 429s) with exponential backoff."""

    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0  # also the longest Retry-After we are willing to wait

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("Invalid retry policy.")

    def backoff(self, attempt: int) -> float:
        return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)


DEFAULT_RETRY = RetryPolicy()
Sleep = Callable[[float], Awaitable[None]]


def _snippet(body: bytes, limit: int = 200) -> str:
    text = " ".join(body.decode("utf-8", errors="replace").split())
    return text[:limit]


def _retry_after(headers: Mapping[str, str]) -> float | None:
    try:
        value = float(headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None


def classify_response(
    provider: str, resp: HttpResponse, quota_statuses: frozenset[int] = frozenset()
) -> ProviderError | None:
    """Map an HTTP response to a ProviderError, or None for success (2xx)."""
    status = resp.status
    if 200 <= status < 300:
        return None
    if status in (401, 403):
        return ProviderAuthError(provider, f"authentication failed (HTTP {status})")
    if status in quota_statuses:
        return ProviderQuotaExceeded(provider, f"plan or usage limit exceeded (HTTP {status})")
    if status == 429:
        return ProviderRateLimited(
            provider, "rate limited (HTTP 429)", retry_after=_retry_after(resp.headers)
        )
    if 500 <= status < 600:
        return ProviderUnavailable(provider, f"server error (HTTP {status})")
    return ProviderBadResponse(provider, f"request rejected (HTTP {status}): {_snippet(resp.body)}")


async def post_json_with_retry(
    client: HttpClient,
    *,
    provider: str,
    url: str,
    headers: Mapping[str, str],
    body: Any,
    timeout: float,
    retry: RetryPolicy = DEFAULT_RETRY,
    quota_statuses: frozenset[int] = frozenset(),
    sleep: Sleep = asyncio.sleep,
) -> Any:
    """POST JSON and return the parsed JSON response, or raise a `ProviderError`."""
    for attempt in range(1, retry.max_attempts + 1):
        try:
            resp = await client.post_json(url, headers=headers, body=body, timeout=timeout)
        except HttpTransportError as exc:
            error: ProviderError | None = ProviderUnavailable(provider, f"network error: {exc}")
        else:
            error = classify_response(provider, resp, quota_statuses)
            if error is None:
                try:
                    return resp.json()
                except ValueError:
                    raise ProviderBadResponse(provider, "response was not valid JSON") from None

        assert error is not None
        delay = retry.backoff(attempt)
        if isinstance(error, ProviderRateLimited) and error.retry_after is not None:
            delay = error.retry_after
        retryable = isinstance(error, ProviderUnavailable | ProviderRateLimited)
        too_long = delay > retry.max_delay
        if not retryable or too_long or attempt == retry.max_attempts:
            log.warning(
                "provider call failed",
                extra={"provider": provider, "attempt": attempt, "error": type(error).__name__},
            )
            raise error
        log.info(
            "provider call retrying",
            extra={"provider": provider, "attempt": attempt, "delay_s": delay},
        )
        await sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover