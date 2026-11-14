import asyncio
from datetime import UTC, datetime

import pytest

from app.engine.providers.errors import FetchError, UnsafeURLError
from app.engine.providers.fake import FakeFetcher
from app.engine.providers.fetcher import (
    HttpPageFetcher,
    check_public_url,
    is_public_ip,
)
from app.engine.providers.http import HttpResponse, HttpTransportError

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
HTML = (
    '<html><head><title>Acme CEO</title><meta property="article:published_time" '
    'content="2026-10-01"></head><body><p>Jane Roe is the CEO of Acme.</p></body></html>'
)


def html_response(body=HTML, status=200, ctype="text/html; charset=utf-8", **headers):
    return HttpResponse(status, body.encode(), {"content-type": ctype, **headers})


class FakeGet:
    """Scripted GET: routes maps url -> HttpResponse | exception, or a list used in order."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    async def get(self, url, *, headers, timeout, max_bytes):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout, "max": max_bytes})
        item = self.routes[url] if isinstance(self.routes, dict) else self.routes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def public_dns(host):
    return ["93.184.216.34"]


def fetcher(routes, resolver=public_dns, **kw):
    return HttpPageFetcher(FakeGet(routes), resolver=resolver, clock=lambda: NOW, **kw)


def fetch(f, url="https://example.com/a"):
    return asyncio.run(f.fetch(url))


def test_fetches_text_title_date_and_final_url():
    f = fetcher({"https://example.com/a": html_response()})
    doc = fetch(f)
    assert str(doc.url) == "https://example.com/a" and doc.title == "Acme CEO"
    assert doc.text == "Jane Roe is the CEO of Acme."
    assert doc.published_at == datetime(2026, 10, 1, tzinfo=UTC) and doc.fetched_at == NOW


def test_request_is_polite_and_bounded():
    f = fetcher({"https://example.com/a": html_response()}, timeout=7, max_bytes=999)
    fetch(f)
    call = f._http.calls[0]
    assert "FreshGuardBot" in call["headers"]["user-agent"]
    assert (call["timeout"], call["max"]) == (7, 999)


def test_custom_user_agent_is_sent():
    f = fetcher(
        {"https://example.com/a": html_response()}, user_agent="FreshGuardBot/0.1 (+me@x.org)"
    )
    fetch(f)
    assert f._http.calls[0]["headers"]["user-agent"] == "FreshGuardBot/0.1 (+me@x.org)"


def test_user_agent_for_contact():
    from app.engine.providers.factory import user_agent_for
    from app.engine.providers.fetcher import USER_AGENT

    assert user_agent_for("") == USER_AGENT
    assert user_agent_for("  me@x.org ") == "FreshGuardBot/0.1 (+me@x.org)"


def test_redirects_are_followed_and_every_hop_is_checked():
    routes = {
        "https://example.com/a": HttpResponse(301, b"", {"location": "/b"}),
        "https://example.com/b": HttpResponse(302, b"", {"location": "https://other.org/c"}),
        "https://other.org/c": html_response(),
    }
    f = fetcher(routes)
    assert str(fetch(f).url) == "https://other.org/c"
    assert [c["url"] for c in f._http.calls] == list(routes)


def test_redirect_to_an_internal_address_is_blocked():
    routes = {
        "https://example.com/a": HttpResponse(
            302, b"", {"location": "http://169.254.169.254/latest/meta-data"}
        )
    }
    with pytest.raises(UnsafeURLError):
        fetch(fetcher(routes))


def test_redirect_loop_is_cut_off():
    routes = {"https://example.com/a": HttpResponse(302, b"", {"location": "/a"})}
    with pytest.raises(FetchError, match="too many redirects"):
        fetch(fetcher(routes, max_redirects=3))


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost/admin",
        "http://app.localhost/",
        "http://printer.local/",
        "http://db.internal/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "https:///nohost",
    ],
)
def test_unsafe_urls_are_refused_before_any_request(url):
    f = fetcher({})
    with pytest.raises(UnsafeURLError):
        fetch(f, url)
    assert f._http.calls == []


def test_hostnames_resolving_to_private_addresses_are_refused():
    async def sneaky(host):
        return ["93.184.216.34", "10.1.2.3"]  # one bad address is enough

    with pytest.raises(UnsafeURLError):
        fetch(fetcher({}, resolver=sneaky))


def test_dns_failure_is_a_fetch_error():
    async def broken(host):
        raise OSError("no such host")

    with pytest.raises(FetchError, match="resolved") as info:
        fetch(fetcher({}, resolver=broken))
    assert not isinstance(info.value, UnsafeURLError)


@pytest.mark.parametrize(
    ("ip", "public"),
    [("93.184.216.34", True), ("8.8.8.8", True), ("2606:4700::1111", True), ("10.0.0.1", False),
     ("172.16.0.1", False), ("100.64.0.1", False), ("127.0.0.1", False), ("224.0.0.1", False),
     ("::1", False), ("fe80::1", False), ("::ffff:10.0.0.1", False), ("junk", False)],
)  # fmt: skip
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


def test_check_public_url_returns_the_url_for_a_public_host():
    assert asyncio.run(check_public_url("https://example.com/x", public_dns)) == (
        "https://example.com/x"
    )


@pytest.mark.parametrize("status", [404, 403, 500, 429])
def test_http_errors(status):
    with pytest.raises(FetchError, match=f"HTTP {status}"):
        fetch(fetcher({"https://example.com/a": HttpResponse(status, b"nope")}))


def test_network_failure():
    with pytest.raises(FetchError, match="network error"):
        fetch(fetcher({"https://example.com/a": HttpTransportError("request timed out")}))


@pytest.mark.parametrize("ctype", ["application/pdf", "image/png", "application/json"])
def test_unsupported_content_types(ctype):
    with pytest.raises(FetchError, match="unsupported content type"):
        fetch(fetcher({"https://example.com/a": html_response("x", ctype=ctype)}))


def test_plain_text_pages():
    doc = fetch(
        fetcher(
            {"https://example.com/a": html_response("  line  one\n\nline two", ctype="text/plain")}
        )
    )
    assert doc.text == "line one\nline two" and doc.published_at is None and doc.title is None


def test_empty_pages_are_errors():
    with pytest.raises(FetchError, match="no readable text"):
        fetch(
            fetcher({"https://example.com/a": html_response("<html><script>x()</script></html>")})
        )


def test_declared_charset_is_honoured_and_bad_ones_fall_back():
    latin = HttpResponse(
        200, "<p>café</p>".encode("latin-1"), {"content-type": "text/html; charset=latin-1"}
    )
    assert fetch(fetcher({"https://example.com/a": latin})).text == "café"
    weird = HttpResponse(200, b"<p>ok</p>", {"content-type": "text/html; charset=nonsense-9"})
    assert fetch(fetcher({"https://example.com/a": weird})).text == "ok"


def test_text_is_capped():
    big = "<p>" + "word " * 60_000 + "</p>"
    assert len(fetch(fetcher({"https://example.com/a": html_response(big)})).text) <= 100_000


def test_fake_fetcher():
    f = FakeFetcher({"https://a.com/x": "page text", "https://a.com/boom": FetchError("boom")})
    assert fetch(f, "https://a.com/x").text == "page text"
    with pytest.raises(FetchError, match="boom"):
        fetch(f, "https://a.com/boom")
    with pytest.raises(FetchError, match="404"):
        fetch(f, "https://a.com/missing")
    assert len(f.calls) == 3


LM = {"last-modified": "Tue, 03 Nov 2026 10:00:00 GMT"}


def test_last_modified_header_becomes_modified_at_when_page_has_none():
    page = "<html><body><p>Chancellor since 2025.</p></body></html>"
    f = fetcher({"https://example.com/a": html_response(page, **LM)})
    doc = fetch(f)
    assert doc.modified_at == datetime(2026, 11, 3, 10, tzinfo=UTC) and doc.published_at is None


def test_page_metadata_beats_last_modified_header_and_junk_header_is_ignored():
    html = '<meta property="article:modified_time" content="2026-10-20"><p>Some page text here.</p>'
    f = fetcher({"https://example.com/a": html_response(html, **LM)})
    assert fetch(f).modified_at == datetime(2026, 10, 20, tzinfo=UTC)
    f = fetcher({"https://example.com/a": html_response(HTML, **{"last-modified": "garbage"})})
    assert fetch(f).modified_at is None