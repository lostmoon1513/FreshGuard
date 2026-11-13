"""A scripted transport (sync and async) and sample API payloads. No network."""

from __future__ import annotations

from typing import Any

from freshguard._core import Response
from freshguard.errors import ConnectionFailed

PENDING = {"id": "abc123", "status": "pending"}

COMPLETED = {
    "id": "abc123",
    "status": "completed",
    "label": "stale",
    "confidence": 0.81,
    "suggested_correction": "Priya Raman is the chief executive of Acme Corp.",
    "error": None,
    "created_at": "2026-11-13T03:30:00Z",
    "finished_at": "2026-11-13T03:30:24Z",
    "metadata": {"message_id": "m-7"},
    "claims": [
        {
            "text": "Jon Lee is the chief executive of Acme Corp",
            "volatility": "slow",
            "label": "stale",
            "reasoning": "A credible, recent source contradicts the claim.",
            "freshness_window_days": 365,
            "evidence": [
                {
                    "url": "https://www.reuters.com/acme",
                    "tier": 2,
                    "published_at": "2026-02-20T00:00:00Z",
                    "fetched_at": "2026-11-13T03:30:12Z",
                    "stance": "contradicts",
                    "quoted_span": "Priya Raman was appointed chief executive of Acme Corp",
                    "integrity_ok": True,
                }
            ],
        }
    ],
}

FAILED = {
    "id": "abc123",
    "status": "failed",
    "error": "Search or model providers were unavailable.",
}


def ok(body: Any, status: int = 200, **headers: str) -> Response:
    return Response(status, body, {k.replace("_", "-"): v for k, v in headers.items()})


def err(status: int, code: str, message: str, **headers: str) -> Response:
    body = {"error": {"code": code, "message": message}}
    return Response(status, body, {k.replace("_", "-"): v for k, v in headers.items()})


class FakeTransport:
    """Replays scripted replies in order. Each item is a Response or an exception to raise."""

    def __init__(self, *replies: Response | Exception) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def _next(self, method, url, headers, json, params, timeout):
        self.calls.append(
            {"method": method, "url": url, "headers": headers, "json": json,
             "params": params, "timeout": timeout}
        )  # fmt: skip
        if not self._replies:
            raise AssertionError("FakeTransport: no reply scripted")
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def request(self, method, url, *, headers, json=None, params=None, timeout):
        return self._next(method, url, headers, json, params, timeout)

    def close(self) -> None:
        self.closed = True


class FakeAsyncTransport(FakeTransport):
    async def request(self, method, url, *, headers, json=None, params=None, timeout):  # type: ignore[override]
        return self._next(method, url, headers, json, params, timeout)

    async def aclose(self) -> None:
        self.closed = True


class Clock:
    """Fake time: `sleep` advances it, so wait loops run instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    async def asleep(self, seconds: float) -> None:
        self.sleep(seconds)


DOWN = ConnectionFailed("Could not reach the FreshGuard server (network error).")