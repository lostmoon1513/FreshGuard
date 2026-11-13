"""httpx-backed transports. The only module that imports httpx."""

from __future__ import annotations

from typing import Any

import httpx

from freshguard._core import Response
from freshguard.errors import ConnectionFailed


def _response(resp: httpx.Response) -> Response:
    try:
        body = resp.json()
    except ValueError:
        body = None
    return Response(resp.status_code, body, {k.lower(): v for k, v in resp.headers.items()})


def _connection_error(exc: httpx.HTTPError) -> ConnectionFailed:
    kind = "timed out" if isinstance(exc, httpx.TimeoutException) else "network error"
    return ConnectionFailed(f"Could not reach the FreshGuard server ({kind}).")


class HttpxTransport:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float,
    ) -> Response:
        try:
            resp = self._client.request(
                method, url, headers=headers, json=json, params=params, timeout=timeout
            )
        except httpx.HTTPError as exc:
            raise _connection_error(exc) from None
        return _response(resp)

    def close(self) -> None:
        self._client.close()


class HttpxAsyncTransport:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient()

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: Any = None,
        params: dict[str, Any] | None = None,
        timeout: float,
    ) -> Response:
        try:
            resp = await self._client.request(
                method, url, headers=headers, json=json, params=params, timeout=timeout
            )
        except httpx.HTTPError as exc:
            raise _connection_error(exc) from None
        return _response(resp)

    async def aclose(self) -> None:
        await self._client.aclose()