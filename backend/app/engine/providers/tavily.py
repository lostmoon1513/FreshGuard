"""Tavily search provider (primary). Returns page text so quotes can be verified against it.

Docs: POST https://api.tavily.com/search, `Authorization: Bearer <key>`. 429 = rate limit,
432/433 = plan/pay-as-you-go limit. `published_date` is only present for some results (it is
automatic for topic="news"); a missing date is passed on as None, never guessed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import SecretStr

from app.engine.providers._hits import build_hits
from app.engine.providers.dates import parse_published_date
from app.engine.providers.errors import ProviderBadResponse
from app.engine.providers.http import (
    DEFAULT_RETRY,
    HttpClient,
    RetryPolicy,
    Sleep,
    post_json_with_retry,
)
from app.engine.providers.models import SearchHit, utc_now
from app.engine.providers.secrets import secret_value

DEFAULT_URL = "https://api.tavily.com/search"
MAX_RESULTS_LIMIT = 20


class TavilySearch:
    name = "tavily"

    def __init__(
        self,
        api_key: SecretStr | str,
        client: HttpClient,
        *,
        topic: Literal["general", "news", "finance"] = "general",
        search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "basic",
        include_raw_content: bool = True,
        retry: RetryPolicy = DEFAULT_RETRY,
        timeout: float = 20.0,
        url: str = DEFAULT_URL,
        clock: Callable[[], datetime] = utc_now,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._key = secret_value(api_key)
        self._client = client
        self._topic = topic
        self._depth = search_depth
        self._raw = include_raw_content
        self._retry = retry
        self._timeout = timeout
        self._url = url
        self._clock = clock
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"TavilySearch(topic={self._topic!r}, depth={self._depth!r})"

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        limit = max(1, min(max_results, MAX_RESULTS_LIMIT))
        body: dict[str, Any] = {
            "query": query,
            "max_results": limit,
            "search_depth": self._depth,
            "topic": self._topic,
        }
        if self._raw:
            body["include_raw_content"] = "text"
        data = await post_json_with_retry(
            self._client,
            provider=self.name,
            url=self._url,
            headers={"authorization": f"Bearer {self._key}", "content-type": "application/json"},
            body=body,
            timeout=self._timeout,
            retry=self._retry,
            quota_statuses=frozenset({432, 433}),
            sleep=self._sleep,
        )
        return hits_from_tavily(
            data, now=self._clock(), limit=limit, with_raw=self._raw, provider=self.name
        )


def hits_from_tavily(
    data: Any, *, now: datetime, limit: int, with_raw: bool, provider: str = "tavily"
) -> list[SearchHit]:
    """Turn a Tavily response dict (REST or LangChain tool output) into SearchHits."""
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise ProviderBadResponse(provider, "response had no 'results' list")
    return build_hits(
        provider,
        results,
        url_key="url",
        snippet_key="content",
        content_key="raw_content" if with_raw else None,
        date_of=lambda item: parse_published_date(_as_str(item.get("published_date")), now),
        retrieved_at=now,
        max_results=limit,
    )


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None