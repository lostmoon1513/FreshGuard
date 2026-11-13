"""Everything a node needs from the outside world, passed in explicitly (no globals)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.engine.providers.fetcher import PageFetcher
from app.engine.providers.models import LLMProvider, ModelTier, SearchProvider, T, utc_now
from app.engine.rules.windows import DEFAULT_POLICY, FreshnessPolicy


@dataclass(frozen=True)
class Limits:
    """Budgets that keep one verification inside free-tier quotas and sane latency."""

    max_claims: int = 8
    max_claim_chars: int = 300
    max_queries_per_claim: int = 3
    results_per_query: int = 5
    max_hits_per_claim: int = 12
    max_candidates: int = 8  # hits considered after ranking
    max_sources_per_claim: int = 5  # sources sent to the stance model
    max_fetches_per_claim: int = 4
    passage_chars: int = 2500
    max_correction_chars: int = 400
    llm_concurrency: int = 3
    search_concurrency: int = 4
    fetch_concurrency: int = 4


@dataclass
class Deps:
    llm: LLMProvider
    search: SearchProvider
    fetcher: PageFetcher | None = None  # None: only hits that already carry page text are usable
    clock: Callable[[], datetime] = utc_now
    policy: FreshnessPolicy = DEFAULT_POLICY
    limits: Limits = field(default_factory=Limits)

    def __post_init__(self) -> None:
        self.llm_slots = asyncio.Semaphore(self.limits.llm_concurrency)
        self.search_slots = asyncio.Semaphore(self.limits.search_concurrency)
        self.fetch_slots = asyncio.Semaphore(self.limits.fetch_concurrency)

    async def llm_call(
        self, *, system: str, prompt: str, response_model: type[T], tier: ModelTier
    ) -> T:
        """One structured LLM call, bounded by the concurrency limit."""
        async with self.llm_slots:
            return await self.llm.generate_structured(
                system=system, prompt=prompt, response_model=response_model, tier=tier
            )