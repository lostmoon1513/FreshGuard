"""Search-result cache: protects free-tier quotas and removes duplicate queries.

- Keyed on normalized query + max_results + provider name.
- TTL is deliberately short (default 6 h, set in Settings): a long TTL would defeat freshness
  monitoring by serving stale search results.
- Empty results and errors are never cached (they are often transient).
- Single-flight: concurrent identical queries (per-claim fan-out) trigger ONE provider call.
- Cached hits keep their original `retrieved_at`, so evidence age is never disguised.
`SearchCache` is a Protocol so a database-backed cache can be added in M5 without touching this.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol

from app.engine.providers.models import SearchHit, SearchProvider


def make_cache_key(provider: str, query: str, max_results: int) -> str:
    return f"{provider}|{max_results}|{' '.join(query.lower().split())}"


class SearchCache(Protocol):
    async def get(self, key: str) -> list[SearchHit] | None: ...

    async def set(self, key: str, hits: list[SearchHit], ttl_seconds: float) -> None: ...


class InMemoryTTLCache:
    def __init__(
        self, max_entries: int = 1000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max = max_entries
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, tuple[SearchHit, ...]]] = OrderedDict()

    async def get(self, key: str) -> list[SearchHit] | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, hits = item
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return list(hits)

    async def set(self, key: str, hits: list[SearchHit], ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        self._data[key] = (self._clock() + ttl_seconds, tuple(hits))
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


class CachedSearch:
    def __init__(
        self, inner: SearchProvider, cache: SearchCache, *, ttl_seconds: float = 6 * 3600.0
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_seconds
        self._locks: dict[str, list] = {}  # key -> [lock, waiter_count]
        self.name = inner.name

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        key = make_cache_key(self._inner.name, query, max_results)
        cached = await self._cache.get(key)
        if cached is not None:
            return cached

        entry = self._locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                cached = await self._cache.get(key)  # another caller may have filled it
                if cached is not None:
                    return cached
                hits = await self._inner.search(query, max_results=max_results)
                if hits:
                    await self._cache.set(key, hits, self._ttl)
                return hits
        finally:
            entry[1] -= 1
            if entry[1] == 0:
                self._locks.pop(key, None)