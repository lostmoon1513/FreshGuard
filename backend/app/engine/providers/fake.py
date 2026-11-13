"""Fake providers. FOR TESTS ONLY.

They never run in production (`Settings` rejects `fake`, and the factory re-checks) and their
output is never presented as a real result. They fail loudly rather than invent data: a
`FakeLLM` with an exhausted script raises instead of making something up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.engine.providers.errors import FetchError
from app.engine.providers.models import ModelTier, SearchHit, T
from app.schemas.evidence import Document

FAKE_NOW = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class FakeLLMCall:
    system: str
    prompt: str
    response_model: type[BaseModel]
    tier: ModelTier


class FakeLLM:
    """Replays a script: each item is a model instance, a dict (validated), or an Exception
    (raised). Or pass a callable `(call) -> model | dict` for dynamic replies."""

    name = "fake"

    def __init__(
        self,
        script: Sequence[BaseModel | Mapping[str, Any] | Exception]
        | Callable[[FakeLLMCall], BaseModel | Mapping[str, Any]] = (),
    ) -> None:
        self._script = script
        self._index = 0
        self.calls: list[FakeLLMCall] = []

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tier: ModelTier = ModelTier.STANDARD,
    ) -> T:
        call = FakeLLMCall(system, prompt, response_model, tier)
        self.calls.append(call)
        if callable(self._script):
            item: Any = self._script(call)
        else:
            if self._index >= len(self._script):
                raise AssertionError("FakeLLM script exhausted: no reply scripted for this call.")
            item = self._script[self._index]
            self._index += 1
        if isinstance(item, Exception):
            raise item
        if isinstance(item, response_model):
            return item
        return response_model.model_validate(item)


def make_hit(
    url: str,
    text: str,
    *,
    published_at: datetime | None = None,
    title: str = "",
    retrieved_at: datetime = FAKE_NOW,
) -> SearchHit:
    """Build a SearchHit for tests (text goes in `content`)."""
    return SearchHit(
        url=url,
        title=title,
        content=text,
        published_at=published_at,
        retrieved_at=retrieved_at,
        provider="fake",
    )


class FakeSearch:
    """Returns scripted hits per query (case/whitespace-insensitive); unknown queries -> []."""

    name = "fake"

    def __init__(
        self,
        results: Mapping[str, Sequence[SearchHit]]
        | Callable[[str, int], Sequence[SearchHit]]
        | None = None,
    ) -> None:
        self._results = results if results is not None else {}
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        self.calls.append((query, max_results))
        if callable(self._results):
            found = self._results(query, max_results)
        else:
            norm = {" ".join(k.lower().split()): v for k, v in self._results.items()}
            found = norm.get(" ".join(query.lower().split()), [])
        return list(found)[:max_results]


class FakeFetcher:
    """Serves scripted pages by exact URL. A value is a Document, a str (page text) or an
    Exception to raise. Unknown URLs raise FetchError, like a 404."""

    name = "fake"

    def __init__(self, pages: Mapping[str, Document | str | Exception] | None = None) -> None:
        self._pages = dict(pages or {})
        self.calls: list[str] = []

    async def fetch(self, url: str) -> Document:
        self.calls.append(url)
        item = self._pages.get(url)
        if item is None:
            raise FetchError("HTTP 404", url)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, Document):
            return item
        return Document(url=url, text=item, fetched_at=FAKE_NOW)  # type: ignore[arg-type]