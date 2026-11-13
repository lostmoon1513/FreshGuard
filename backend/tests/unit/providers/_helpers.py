"""Test helpers: a scripted HTTP client and a recording sleeper. No network anywhere."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from app.engine.providers.http import HttpResponse, HttpTransportError


class Verdict(BaseModel):
    """A small response model used by the LLM tests."""

    answer: str
    score: int


def ok(data: Any) -> HttpResponse:
    return HttpResponse(200, json.dumps(data).encode())


def status(code: int, *, headers: Mapping[str, str] | None = None, body: str = "") -> HttpResponse:
    return HttpResponse(code, body.encode(), {k.lower(): v for k, v in (headers or {}).items()})


class FakeHttp:
    """Replays scripted replies in order; each is an HttpResponse or an exception to raise."""

    def __init__(self, *replies: HttpResponse | HttpTransportError) -> None:
        self._replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def post_json(
        self, url: str, *, headers: Mapping[str, str], body: Any, timeout: float
    ) -> HttpResponse:
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "timeout": timeout})
        if not self._replies:
            raise AssertionError("FakeHttp: no scripted reply left")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def gemini_reply(text: str) -> HttpResponse:
    return ok({"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})


def groq_reply(text: str) -> HttpResponse:
    return ok({"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})