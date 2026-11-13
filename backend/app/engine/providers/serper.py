"""Serper.dev search provider (fallback). Google results; snippet text only (no page content).

Docs: POST https://google.serper.dev/search, header `X-API-KEY`, body {"q", "num"}.
Organic results carry `link`, `title`, `snippet` and sometimes `date` (e.g. "Jan 5, 2025" or
"3 days ago"), parsed by `parse_published_date`; unreadable dates become None.
Quotes can only come from the snippet, so evidence from Serper is thinner than from Tavily.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

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

DEFAULT_URL = "https://google.serper.dev/search"
MAX_RESULTS_LIMIT = 20


class SerperSearch:
    name = "serper"

    def __init__(
        self,
        api_key: SecretStr | str,
        client: HttpClient,
        *,
        retry: RetryPolicy = DEFAULT_RETRY,
        timeout: float = 20.0,
        url: str = DEFAULT_URL,
        clock: Callable[[], datetime] = utc_now,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._key = secret_value(api_key)
        self._client = client
        self._retry = retry
        self._timeout = timeout
        self._url = url
        self._clock = clock
        self._sleep = sleep

    def __repr__(self) -> str:
        return "SerperSearch()"

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        limit = max(1, min(max_results, MAX_RESULTS_LIMIT))
        data = await post_json_with_retry(
            self._client,
            provider=self.name,
            url=self._url,
            headers={"x-api-key": self._key, "content-type": "application/json"},
            body={"q": query, "num": limit},
            timeout=self._timeout,
            retry=self._retry,
            sleep=self._sleep,
        )
        return hits_from_serper(data, now=self._clock(), limit=limit, provider=self.name)


def hits_from_serper(
    data: Any, *, now: datetime, limit: int, provider: str = "serper"
) -> list[SearchHit]:
    """Turn a Serper response dict (REST or LangChain wrapper output) into SearchHits."""
    organic = data.get("organic") if isinstance(data, dict) else None
    if organic is None and isinstance(data, dict):
        organic = []  # Serper omits 'organic' when there are no results
    if not isinstance(organic, list):
        raise ProviderBadResponse(provider, "response 'organic' was not a list")
    return build_hits(
        provider,
        organic,
        url_key="link",
        snippet_key="snippet",
        content_key=None,
        date_of=lambda item: parse_published_date(_as_str(item.get("date")), now),
        retrieved_at=now,
        max_results=limit,
    )


def _as_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None