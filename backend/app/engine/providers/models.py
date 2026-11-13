"""Provider interfaces and the data types they exchange.

The engine depends on these two Protocols only: `LLMProvider` and `SearchProvider`.
Real clients, fallbacks, caches and fakes all implement them, so any can be swapped in tests.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeVar, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl

T = TypeVar("T", bound=BaseModel)

# Page text is capped so one huge page cannot blow up memory, caches or prompts.
MAX_CONTENT_CHARS = 20_000


class ModelTier(StrEnum):
    """LIGHT = cheap and fast (claim extraction). STANDARD = better reasoning (stance)."""

    LIGHT = "light"
    STANDARD = "standard"


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tier: ModelTier = ModelTier.STANDARD,
    ) -> T:
        """Return a validated `response_model`. Raises `ProviderError` on any failure.

        Implementations must never return unvalidated or partially filled output.
        """
        ...


class SearchHit(BaseModel):
    """One search result as returned by a provider. Not yet a verified `Document`.

    `content` is page text when the provider supplies it (Tavily); otherwise None and only the
    short `snippet` is available (Serper). Quotes may only be taken from this text.
    """

    model_config = ConfigDict(frozen=True)

    url: HttpUrl
    title: str = ""
    snippet: str = ""
    content: str | None = None
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime
    provider: str = Field(min_length=1)

    @property
    def text(self) -> str:
        """The best text we hold for this result ('' if none)."""
        return (self.content or "").strip() or self.snippet.strip()


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        """Return up to `max_results` hits that carry some text. Raises `ProviderError`."""
        ...


def truncate_text(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit]


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)