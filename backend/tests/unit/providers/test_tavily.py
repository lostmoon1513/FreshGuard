import asyncio
from datetime import UTC, datetime

import pytest

from app.engine.providers.errors import (
    ProviderAuthError,
    ProviderBadResponse,
    ProviderQuotaExceeded,
)
from app.engine.providers.models import MAX_CONTENT_CHARS
from app.engine.providers.tavily import TavilySearch
from tests.unit.providers._helpers import FakeHttp, Sleeper, ok, status

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
KEY = "tvly-test"


def make(http, **kw):
    return TavilySearch(KEY, http, clock=lambda: NOW, sleep=Sleeper(), **kw)


def search(provider, query="who is the ceo of acme", n=5):
    return asyncio.run(provider.search(query, max_results=n))


def result(url="https://example.com/a", **over):
    return {"title": "T", "url": url, "content": "snippet text", "score": 0.9, **over}


def test_request_shape():
    http = FakeHttp(ok({"results": []}))
    search(make(http), "  hello  ", 7)
    call = http.calls[0]
    assert call["url"] == "https://api.tavily.com/search"
    assert call["headers"]["authorization"] == f"Bearer {KEY}"
    assert call["body"] == {
        "query": "hello",
        "max_results": 7,
        "search_depth": "basic",
        "topic": "general",
        "include_raw_content": "text",
    }


def test_without_raw_content_flag_is_omitted():
    http = FakeHttp(ok({"results": []}))
    search(make(http, include_raw_content=False))
    assert "include_raw_content" not in http.calls[0]["body"]


@pytest.mark.parametrize(("asked", "sent"), [(0, 1), (-5, 1), (50, 20), (20, 20)])
def test_max_results_is_clamped(asked, sent):
    http = FakeHttp(ok({"results": []}))
    search(make(http), n=asked)
    assert http.calls[0]["body"]["max_results"] == sent


def test_parses_hits_with_page_text_and_dates():
    data = {
        "results": [
            result(raw_content="full page text", published_date="2026-11-01T09:00:00Z"),
            result("https://example.com/b", published_date="Fri, 06 Nov 2026 09:00:00 GMT"),
            result("https://example.com/c", published_date=None),
        ]
    }
    hits = search(make(FakeHttp(ok(data))))
    assert [str(h.url) for h in hits] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert hits[0].content == "full page text" and hits[0].snippet == "snippet text"
    assert hits[0].text == "full page text"
    assert hits[0].published_at == datetime(2026, 11, 1, 9, tzinfo=UTC)
    assert hits[1].content is None and hits[1].text == "snippet text"  # falls back to snippet
    assert hits[1].published_at == datetime(2026, 11, 6, 9, tzinfo=UTC)
    assert hits[2].published_at is None  # no date: never guessed
    assert all(h.provider == "tavily" and h.retrieved_at == NOW for h in hits)


def test_malformed_duplicate_and_textless_results_are_skipped():
    data = {
        "results": [
            result("not a url"),
            result(""),
            {"title": "no url", "content": "x"},
            "garbage",
            None,
            result("https://example.com/empty", content="", raw_content="  "),
            result("https://example.com/ok"),
            result("https://example.com/ok", content="duplicate"),
        ]
    }
    hits = search(make(FakeHttp(ok(data))))
    assert [str(h.url) for h in hits] == ["https://example.com/ok"]


def test_never_returns_more_than_max_results():
    data = {"results": [result(f"https://example.com/{i}") for i in range(10)]}
    assert len(search(make(FakeHttp(ok(data))), n=3)) == 3


def test_huge_pages_are_truncated():
    data = {"results": [result(raw_content="x" * (MAX_CONTENT_CHARS + 500))]}
    (hit,) = search(make(FakeHttp(ok(data))))
    assert len(hit.content) == MAX_CONTENT_CHARS


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": "x"}, [1]])
def test_missing_results_list_is_a_bad_response(payload):
    with pytest.raises(ProviderBadResponse):
        search(make(FakeHttp(ok(payload))))


def test_empty_results_are_fine():
    assert search(make(FakeHttp(ok({"results": []})))) == []


def test_errors_map_correctly():
    with pytest.raises(ProviderAuthError):
        search(make(FakeHttp(status(401))))
    with pytest.raises(ProviderQuotaExceeded):
        search(make(FakeHttp(status(432))))
    with pytest.raises(ProviderQuotaExceeded):
        search(make(FakeHttp(status(433))))


def test_empty_query_is_rejected_before_any_request():
    http = FakeHttp()
    with pytest.raises(ValueError):
        search(make(http), "   ")
    assert http.calls == []


def test_repr_hides_key():
    assert KEY not in repr(make(FakeHttp()))