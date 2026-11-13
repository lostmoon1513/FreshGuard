"""The one place real httpx is used. Skipped automatically if httpx is not installed."""

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from app.engine.providers.errors import ProviderUnavailable  # noqa: E402
from app.engine.providers.gemini import GeminiProvider  # noqa: E402
from app.engine.providers.http import HttpTransportError, RetryPolicy  # noqa: E402
from app.engine.providers.httpx_client import HttpxClient  # noqa: E402
from tests.unit.providers._helpers import Sleeper, Verdict  # noqa: E402


def run_with(handler, coro_factory):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
            return await coro_factory(HttpxClient(raw))

    return asyncio.run(go())


def test_post_json_sends_json_and_returns_status_headers_body():
    seen = {}

    def handler(request):
        seen["url"], seen["headers"], seen["body"] = (
            str(request.url),
            request.headers,
            request.content,
        )
        return httpx.Response(200, json={"ok": True}, headers={"Retry-After": "3"})

    resp = run_with(
        handler,
        lambda c: c.post_json(
            "https://x.test/a", headers={"x-api-key": "k"}, body={"q": 1}, timeout=5
        ),
    )
    assert resp.status == 200 and resp.json() == {"ok": True}
    assert resp.headers["retry-after"] == "3"  # lower-cased names
    assert seen["headers"]["x-api-key"] == "k" and json.loads(seen["body"]) == {"q": 1}


def test_error_statuses_are_returned_not_raised():
    resp = run_with(
        lambda r: httpx.Response(429),
        lambda c: c.post_json("https://x.test", headers={}, body={}, timeout=5),
    )
    assert resp.status == 429


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("c")])
def test_network_failures_become_transport_errors(exc):
    def handler(request):
        raise exc

    with pytest.raises(HttpTransportError):
        run_with(handler, lambda c: c.post_json("https://x.test", headers={}, body={}, timeout=1))


def test_end_to_end_gemini_through_real_httpx_client():
    def handler(request):
        assert request.headers["x-goog-api-key"] == "k"
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"answer": "a", "score": 1}'}]}}]
            },
        )

    async def call(client):
        provider = GeminiProvider("k", client, sleep=Sleeper())
        return await provider.generate_structured(system="s", prompt="p", response_model=Verdict)

    assert run_with(handler, call) == Verdict(answer="a", score=1)


def test_network_failure_surfaces_as_provider_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    async def call(client):
        provider = GeminiProvider("k", client, retry=RetryPolicy(max_attempts=1), sleep=Sleeper())
        await provider.generate_structured(system="s", prompt="p", response_model=Verdict)

    with pytest.raises(ProviderUnavailable):
        run_with(handler, call)


def test_get_streams_body_and_caps_it_without_following_redirects():
    import httpx

    seen = {}

    def handler(request):
        seen["method"], seen["ua"] = request.method, request.headers.get("user-agent")
        return httpx.Response(200, content=b"x" * 5000, headers={"Content-Type": "text/html"})

    async def run():
        http = HttpxClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        resp = await http.get(
            "https://a.com/p", headers={"user-agent": "T"}, timeout=5, max_bytes=1000
        )
        await http.aclose()
        return resp

    resp = asyncio.run(run())
    assert resp.status == 200 and len(resp.body) == 1000
    assert resp.headers["content-type"] == "text/html"
    assert seen == {"method": "GET", "ua": "T"}


def test_get_returns_redirects_instead_of_following_them():
    import httpx

    def handler(request):
        return httpx.Response(302, headers={"Location": "https://b.com/"})

    async def run():
        http = HttpxClient(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        resp = await http.get("https://a.com/p", headers={}, timeout=5, max_bytes=1000)
        await http.aclose()
        return resp

    resp = asyncio.run(run())
    assert resp.status == 302 and resp.headers["location"] == "https://b.com/"


def test_get_maps_timeouts_and_network_errors():
    import httpx

    from app.engine.providers.http import HttpTransportError

    def timeout_handler(request):
        raise httpx.ReadTimeout("slow")

    async def run():
        http = HttpxClient(httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)))
        try:
            await http.get("https://a.com/p", headers={}, timeout=1, max_bytes=10)
        finally:
            await http.aclose()

    with pytest.raises(HttpTransportError, match="timed out"):
        asyncio.run(run())