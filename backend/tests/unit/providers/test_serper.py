import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.engine.providers.errors import ProviderAuthError, ProviderBadResponse
from app.engine.providers.serper import SerperSearch
from tests.unit.providers._helpers import FakeHttp, Sleeper, ok, status

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
KEY = "serper-test"


def make(http):
    return SerperSearch(KEY, http, clock=lambda: NOW, sleep=Sleeper())


def search(provider, query="acme ceo", n=5):
    return asyncio.run(provider.search(query, max_results=n))


def item(link="https://example.com/a", **over):
    return {"title": "T", "link": link, "snippet": "snippet text", "position": 1, **over}


def test_request_shape():
    http = FakeHttp(ok({"organic": []}))
    search(make(http), "  hello ", 4)
    call = http.calls[0]
    assert call["url"] == "https://google.serper.dev/search"
    assert call["headers"]["x-api-key"] == KEY
    assert call["body"] == {"q": "hello", "num": 4}


def test_parses_snippet_only_hits_with_dates():
    data = {
        "organic": [
            item(date="Nov 5, 2026"),
            item("https://example.com/b", date="3 days ago"),
            item("https://example.com/c", date="soon-ish"),
            item("https://example.com/d"),
        ]
    }
    hits = search(make(FakeHttp(ok(data))))
    assert len(hits) == 4
    assert all(h.content is None and h.text == "snippet text" for h in hits)
    assert hits[0].published_at == datetime(2026, 11, 5, tzinfo=UTC)
    assert hits[1].published_at == NOW - timedelta(days=3)
    assert hits[2].published_at is None and hits[3].published_at is None
    assert all(h.provider == "serper" for h in hits)


def test_skips_malformed_empty_and_duplicate_items():
    data = {
        "organic": [
            item("bad url"),
            item(snippet=""),
            "x",
            item("https://example.com/ok"),
            item("https://example.com/ok"),
        ]
    }
    assert [str(h.url) for h in search(make(FakeHttp(ok(data))))] == ["https://example.com/ok"]


def test_missing_organic_means_no_results_not_an_error():
    assert search(make(FakeHttp(ok({"searchParameters": {}})))) == []


@pytest.mark.parametrize("payload", [{"organic": "x"}, [1], "x"])
def test_malformed_payload_is_a_bad_response(payload):
    with pytest.raises(ProviderBadResponse):
        search(make(FakeHttp(ok(payload))))


def test_auth_error():
    with pytest.raises(ProviderAuthError):
        search(make(FakeHttp(status(403))))


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        search(make(FakeHttp()), "")


def test_repr_hides_key():
    assert KEY not in repr(make(FakeHttp()))