import asyncio
from datetime import UTC, datetime

import pytest

from app.engine.providers.cache import CachedSearch, InMemoryTTLCache, make_cache_key
from app.engine.providers.errors import ProviderUnavailable
from app.engine.providers.fake import FakeSearch, make_hit


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class CountingSearch:
    name = "counting"

    def __init__(self, hits=None, error=None, delay=False):
        self.hits = hits if hits is not None else [make_hit("https://example.com/a", "text")]
        self.error, self.delay, self.calls = error, delay, 0

    async def search(self, query, *, max_results):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(0.01)
        if self.error:
            raise self.error
        return list(self.hits)


def make(inner, clock=None, ttl=100.0, max_entries=100):
    clock = clock or Clock()
    return CachedSearch(inner, InMemoryTTLCache(max_entries, clock), ttl_seconds=ttl), clock


def s(provider, q="Acme CEO", n=5):
    return asyncio.run(provider.search(q, max_results=n))


def test_second_identical_query_is_served_from_cache():
    inner = CountingSearch()
    cached, _ = make(inner)
    first = s(cached)
    assert s(cached) == first and inner.calls == 1


def test_key_normalizes_case_and_whitespace_but_not_max_results_or_provider():
    assert make_cache_key("p", "  Acme   CEO ", 5) == make_cache_key("p", "acme ceo", 5)
    assert make_cache_key("p", "q", 5) != make_cache_key("p", "q", 6)
    assert make_cache_key("p", "q", 5) != make_cache_key("other", "q", 5)


def test_normalized_queries_share_an_entry():
    inner = CountingSearch()
    cached, _ = make(inner)
    s(cached, "Acme CEO")
    s(cached, "  acme   ceo ")
    assert inner.calls == 1


def test_different_max_results_are_cached_separately():
    inner = CountingSearch()
    cached, _ = make(inner)
    s(cached, n=5)
    s(cached, n=3)
    assert inner.calls == 2


def test_entries_expire_after_ttl():
    inner = CountingSearch()
    cached, clock = make(inner, ttl=100)
    s(cached)
    clock.now = 99.9
    s(cached)
    assert inner.calls == 1
    clock.now = 100.0
    s(cached)
    assert inner.calls == 2


def test_empty_results_are_not_cached():
    inner = CountingSearch(hits=[])
    cached, _ = make(inner)
    s(cached)
    s(cached)
    assert inner.calls == 2


def test_errors_are_not_cached_and_propagate():
    inner = CountingSearch(error=ProviderUnavailable("x", "down"))
    cached, _ = make(inner)
    for _ in range(2):
        with pytest.raises(ProviderUnavailable):
            s(cached)
    assert inner.calls == 2


def test_ttl_zero_disables_storage():
    inner = CountingSearch()
    cached, _ = make(inner, ttl=0)
    s(cached)
    s(cached)
    assert inner.calls == 2


def test_concurrent_identical_queries_make_one_provider_call():
    inner = CountingSearch(delay=True)
    cached, _ = make(inner)

    async def go():
        return await asyncio.gather(*[cached.search("same query", max_results=5) for _ in range(8)])

    results = asyncio.run(go())
    assert inner.calls == 1 and all(r == results[0] for r in results)
    assert cached._locks == {}  # no lock leak


def test_concurrent_different_queries_run_in_parallel_calls():
    inner = CountingSearch(delay=True)
    cached, _ = make(inner)

    async def go():
        await asyncio.gather(*[cached.search(f"q{i}", max_results=5) for i in range(4)])

    asyncio.run(go())
    assert inner.calls == 4


def test_cached_hits_keep_their_original_retrieved_at():
    old = datetime(2026, 1, 1, tzinfo=UTC)
    inner = CountingSearch(hits=[make_hit("https://example.com/a", "t", retrieved_at=old)])
    cached, _ = make(inner)
    s(cached)
    assert s(cached)[0].retrieved_at == old


def test_cache_returns_a_copy():
    cached, _ = make(CountingSearch())
    s(cached)
    got = s(cached)
    got.clear()
    assert len(s(cached)) == 1


def test_lru_eviction_keeps_most_recently_used():
    inner = CountingSearch()
    cached, _ = make(inner, max_entries=2)
    s(cached, "a")
    s(cached, "b")
    s(cached, "a")  # touch a
    s(cached, "c")  # evicts b
    calls = inner.calls
    s(cached, "a")
    assert inner.calls == calls  # a still cached
    s(cached, "b")
    assert inner.calls == calls + 1  # b was evicted


def test_wrapper_keeps_inner_name_and_works_with_fakes():
    cached, _ = make(FakeSearch({"q": [make_hit("https://example.com/a", "t")]}))
    assert cached.name == "fake" and len(s(cached, "q")) == 1


def test_invalid_cache_size():
    with pytest.raises(ValueError):
        InMemoryTTLCache(0)