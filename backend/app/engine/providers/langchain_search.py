"""SearchProvider adapters backed by LangChain search tools.

Duck-typed like `langchain_llm.py`: the Tavily adapter needs an object with
`async ainvoke({"query": ...})` returning Tavily's response dict; the Serper adapter needs an
object with `async aresults(query)` returning Serper's response dict. Parsing is shared with the
REST providers, so a hit looks identical whichever backend produced it.

Known risk: the LangChain Tavily wrapper may drop `published_date`. If so, hits are simply
undated (never guessed), which lowers verdict quality. Compare with the REST backend using
`scripts/smoke_providers.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.engine.providers.langchain_errors import map_exception
from app.engine.providers.models import SearchHit, utc_now
from app.engine.providers.serper import hits_from_serper
from app.engine.providers.tavily import hits_from_tavily

log = logging.getLogger(__name__)


def _clean(query: str) -> str:
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    return query


class LangChainTavilySearch:
    """`tool` is e.g. `langchain_tavily.TavilySearch(include_raw_content=True)`."""

    name = "tavily"

    def __init__(
        self, tool: Any, *, with_raw: bool = True, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._tool = tool
        self._with_raw = with_raw
        self._clock = clock

    def __repr__(self) -> str:
        return "LangChainTavilySearch()"

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        query = _clean(query)
        try:
            data = await self._tool.ainvoke({"query": query})
        except Exception as exc:  # noqa: BLE001 - see langchain_llm.py
            error = map_exception(self.name, exc)
            log.warning(
                "langchain search failed",
                extra={"provider": self.name, "error": type(error).__name__},
            )
            raise error from None
        return hits_from_tavily(
            data,
            now=self._clock(),
            limit=max(1, max_results),
            with_raw=self._with_raw,
            provider=self.name,
        )


class LangChainSerperSearch:
    """`wrapper` is e.g. `langchain_community.utilities.GoogleSerperAPIWrapper(k=5)`."""

    name = "serper"

    def __init__(self, wrapper: Any, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._wrapper = wrapper
        self._clock = clock

    def __repr__(self) -> str:
        return "LangChainSerperSearch()"

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        query = _clean(query)
        try:
            data = await self._wrapper.aresults(query)
        except Exception as exc:  # noqa: BLE001 - see langchain_llm.py
            error = map_exception(self.name, exc)
            log.warning(
                "langchain search failed",
                extra={"provider": self.name, "error": type(error).__name__},
            )
            raise error from None
        return hits_from_serper(
            data, now=self._clock(), limit=max(1, max_results), provider=self.name
        )