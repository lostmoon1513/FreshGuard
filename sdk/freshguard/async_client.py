"""Asynchronous client (same methods as `FreshGuard`, awaitable)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from freshguard import _core
from freshguard._core import AsyncTransport, Response
from freshguard.errors import ConnectionFailed, VerificationTimeout
from freshguard.models import Page, Verification


class AsyncFreshGuard:
    """async with AsyncFreshGuard(base_url=..., api_key=...) as fg:
    result = await fg.verify(question="...", answer="...")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: AsyncTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = _core.build_headers(api_key)
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._sleep = sleep
        self._clock = clock
        if transport is None:
            from freshguard._http import HttpxAsyncTransport

            transport = HttpxAsyncTransport()
        self._transport = transport

    async def __aenter__(self) -> AsyncFreshGuard:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def health(self) -> bool:
        try:
            return (await self._send("GET", "/health", retry=False)).status == 200
        except ConnectionFailed:
            return False

    async def submit(
        self,
        question: str,
        answer: str,
        *,
        answer_generated_at: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Verification:
        body = _core.submit_body(question, answer, answer_generated_at, metadata)
        resp = await self._send("POST", "/v1/verifications", json=body, retry=False)
        _core.raise_for_response(resp)
        return _core.parse_verification(resp)

    async def get(self, verification_id: str) -> Verification:
        resp = await self._send("GET", f"/v1/verifications/{verification_id}")
        _core.raise_for_response(resp)
        return _core.parse_verification(resp)

    async def wait(
        self,
        verification_id: str,
        timeout: float = 90.0,
        poll_interval: float = _core.DEFAULT_POLL_INTERVAL,
    ) -> Verification:
        started = self._clock()
        while True:
            current = await self.get(verification_id)
            if current.is_done:
                return current
            remaining = timeout - (self._clock() - started)
            if remaining <= 0:
                raise VerificationTimeout(verification_id, timeout)
            await self._sleep(min(poll_interval, remaining))

    async def verify(
        self,
        question: str,
        answer: str,
        *,
        wait_seconds: float = 60.0,
        answer_generated_at: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Verification:
        body = _core.submit_body(question, answer, answer_generated_at, metadata)
        if wait_seconds > _core.MAX_SERVER_WAIT:
            pending = await self.submit(question, answer, metadata=metadata)
            return await self.wait(pending.id, timeout=wait_seconds)
        server_wait = max(1, int(wait_seconds))
        resp = await self._send(
            "POST",
            "/v1/verifications",
            json=body,
            params={"wait": "true", "timeout": server_wait},
            timeout=max(self._timeout, server_wait + 10.0),
            retry=False,
        )
        _core.raise_for_response(resp)
        result = _core.parse_verification(resp)
        if resp.status == 200 or result.is_done:
            return result
        raise VerificationTimeout(result.id, float(server_wait))

    async def list(
        self, *, limit: int = 20, label: str | None = None, before: str | None = None
    ) -> Page:
        resp = await self._send(
            "GET", "/v1/verifications", params=_core.list_params(limit, label, before)
        )
        _core.raise_for_response(resp)
        data = _core.expect_json(resp)
        items = tuple(Verification.from_dict(d) for d in data.get("items") or ())
        return Page(items=items, next_before=data.get("next_before"))

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        retry: bool = True,
    ) -> Response:
        attempts = 1 + (self._max_retries if retry else 0)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                resp = await self._transport.request(
                    method,
                    self._base + path,
                    headers=self._headers,
                    json=json,
                    params=params,
                    timeout=timeout or self._timeout,
                )
            except ConnectionFailed:
                if last:
                    raise
                await self._sleep(_core.backoff_seconds(attempt))
                continue
            if not last and _core.should_retry(resp):
                await self._sleep(_core.backoff_seconds(attempt))
                continue
            return resp
        raise AssertionError("unreachable")