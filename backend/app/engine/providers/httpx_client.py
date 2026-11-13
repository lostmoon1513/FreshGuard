"""The only module that imports `httpx`: a thin adapter implementing `HttpClient`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from app.engine.providers.http import HttpResponse, HttpTransportError


class HttpxClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def post_json(
        self, url: str, *, headers: Mapping[str, str], body: Any, timeout: float
    ) -> HttpResponse:
        try:
            resp = await self._client.post(url, headers=dict(headers), json=body, timeout=timeout)
        except httpx.TimeoutException as exc:
            raise HttpTransportError("request timed out") from exc
        except httpx.HTTPError as exc:
            raise HttpTransportError(type(exc).__name__) from exc
        return HttpResponse(
            status=resp.status_code,
            body=resp.content,
            headers={k.lower(): v for k, v in resp.headers.items()},
        )

    async def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int
    ) -> HttpResponse:
        """GET without following redirects; the body is cut off at `max_bytes` (decoded size)."""
        try:
            async with self._client.stream(
                "GET", url, headers=dict(headers), timeout=timeout, follow_redirects=False
            ) as resp:
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    if size + len(chunk) > max_bytes:
                        chunks.append(chunk[: max_bytes - size])
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                return HttpResponse(
                    status=resp.status_code,
                    body=b"".join(chunks),
                    headers={k.lower(): v for k, v in resp.headers.items()},
                )
        except httpx.TimeoutException as exc:
            raise HttpTransportError("request timed out") from exc
        except httpx.HTTPError as exc:
            raise HttpTransportError(type(exc).__name__) from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()