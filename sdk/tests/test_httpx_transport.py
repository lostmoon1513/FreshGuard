"""Adapter tests with httpx's own MockTransport. Skipped where httpx is not installed."""

import pytest

httpx = pytest.importorskip("httpx")

from freshguard import AsyncFreshGuard, ConnectionFailed, FreshGuard  # noqa: E402
from freshguard._http import HttpxAsyncTransport, HttpxTransport  # noqa: E402
from tests._fakes import COMPLETED, PENDING  # noqa: E402


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/verifications" and request.method == "POST":
        assert request.headers["x-api-key"] == "k"
        assert request.url.params.get("wait") == "true"
        return httpx.Response(200, json=COMPLETED, headers={"X-Request-ID": "r1"})
    if request.url.path == "/v1/verifications/abc123":
        return httpx.Response(200, json=PENDING)
    if request.url.path == "/boom":
        raise httpx.ConnectTimeout("slow")
    if request.url.path == "/html":
        return httpx.Response(502, text="<html>bad gateway</html>")
    return httpx.Response(404, json={"error": {"code": "not_found", "message": "nope"}})


def test_sync_end_to_end_over_httpx_mock():
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with FreshGuard("http://api.test", "k", transport=HttpxTransport(client)) as fg:
        v = fg.verify("Q?", "A.", wait_seconds=5)
        assert v.is_stale and v.claims[0].evidence[0].integrity_ok is True
        assert fg.get("abc123").status == "pending"


def test_timeouts_become_connection_failed_and_html_becomes_none_body():
    transport = HttpxTransport(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(ConnectionFailed):
        transport.request("GET", "http://api.test/boom", headers={}, timeout=1)
    resp = transport.request("GET", "http://api.test/html", headers={}, timeout=1)
    assert resp.status == 502 and resp.body is None


async def test_async_end_to_end_over_httpx_mock():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    async with AsyncFreshGuard("http://api.test", "k", transport=HttpxAsyncTransport(client)) as fg:
        v = await fg.verify("Q?", "A.", wait_seconds=5)
        assert v.is_stale