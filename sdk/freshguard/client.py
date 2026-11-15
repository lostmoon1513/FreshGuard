"""Synchronous client."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from freshguard import _core
from freshguard._core import Response, Transport
from freshguard.errors import ConnectionFailed, VerificationTimeout
from freshguard.models import Page, Verification


class FreshGuard:
    """Thin client for the FreshGuard API. All verification logic runs on the server.

    fg = FreshGuard(base_url="http://localhost:8000", api_key="dev-key")
    result = fg.verify(question="...", answer="...", wait_seconds=90)
    if result.should_warn:
        print(result.suggested_correction)
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 2,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = _core.build_headers(api_key)
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._sleep = sleep
        self._clock = clock
        if transport is None:
            from freshguard._http import HttpxTransport

            transport = HttpxTransport()
        self._transport = transport

    def __enter__(self) -> FreshGuard:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    # ---- public API ------------------------------------------------------------------------
    def health(self) -> bool:
        """True if the server answers /health."""
        try:
            return self._send("GET", "/health", retry=False).status == 200
        except ConnectionFailed:
            return False

    def submit(
        self,
        question: str,
        answer: str,
        *,
        answer_generated_at: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Verification:
        """Start a verification and return at once (status "pending"). Not retried: a retry
        could create a duplicate job."""
        body = _core.submit_body(question, answer, answer_generated_at, metadata)
        resp = self._send("POST", "/v1/verifications", json=body, retry=False)
        _core.raise_for_response(resp)
        return _core.parse_verification(resp)

    def reverify(self, verification_id: str) -> Verification:
        """Check the same question and answer again. Starts a NEW verification (status
        "pending") whose metadata has `reverified_from`. Not retried (could duplicate)."""
        resp = self._send("POST", f"/v1/verifications/{verification_id}/reverify", retry=False)
        _core.raise_for_response(resp)
        return _core.parse_verification(resp)

    def get(self, verification_id: str) -> Verification:
        resp = self._send("GET", f"/v1/verifications/{verification_id}")
        _core.raise_for_response(resp)
        return _core.parse_verification(resp)

    def wait(
        self,
        verification_id: str,
        timeout: float = 90.0,
        poll_interval: float = _core.DEFAULT_POLL_INTERVAL,
    ) -> Verification:
        """Poll until the job finishes. Raises `VerificationTimeout` (the job keeps running)."""
        started = self._clock()
        while True:
            current = self.get(verification_id)
            if current.is_done:
                return current
            remaining = timeout - (self._clock() - started)
            if remaining <= 0:
                raise VerificationTimeout(verification_id, timeout)
            self._sleep(min(poll_interval, remaining))

    def verify(
        self,
        question: str,
        answer: str,
        *,
        wait_seconds: float = 60.0,
        answer_generated_at: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Verification:
        """Submit and wait for the result. A finished-but-failed job is returned with
        `status == "failed"` (check `.error`), not raised. Raises `VerificationTimeout` if it
        is not done within `wait_seconds`."""
        body = _core.submit_body(question, answer, answer_generated_at, metadata)
        if wait_seconds > _core.MAX_SERVER_WAIT:
            pending = self.submit(question, answer, metadata=metadata)
            return self.wait(pending.id, timeout=wait_seconds)
        server_wait = max(1, int(wait_seconds))
        resp = self._send(
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

    def list(self, *, limit: int = 20, label: str | None = None, before: str | None = None) -> Page:
        resp = self._send(
            "GET", "/v1/verifications", params=_core.list_params(limit, label, before)
        )
        _core.raise_for_response(resp)
        data = _core.expect_json(resp)
        items = tuple(Verification.from_dict(d) for d in data.get("items") or ())
        return Page(items=items, next_before=data.get("next_before"))

    # ---- internals -------------------------------------------------------------------------
    def _send(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
        retry: bool = True,
    ) -> Response:
        """One request. Safe (GET) requests are retried on network errors and 5xx."""
        attempts = 1 + (self._max_retries if retry else 0)
        for attempt in range(attempts):
            last = attempt == attempts - 1
            try:
                resp = self._transport.request(
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
                self._sleep(_core.backoff_seconds(attempt))
                continue
            if not last and _core.should_retry(resp):
                self._sleep(_core.backoff_seconds(attempt))
                continue
            return resp
        raise AssertionError("unreachable")