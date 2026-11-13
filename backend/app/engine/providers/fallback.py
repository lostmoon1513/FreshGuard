"""Primary -> fallback wrappers with a cooldown, so a rate-limited primary is not hammered.

On any `ProviderError` from the primary the fallback is tried. After a rate limit, quota, auth or
availability failure the primary is skipped for `cooldown_seconds` (protects free-tier quotas and
latency). A single bad LLM output does not start a cooldown. If both fail, `AllProvidersFailed`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.engine.providers.errors import (
    AllProvidersFailed,
    ProviderAuthError,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.engine.providers.models import LLMProvider, ModelTier, SearchHit, SearchProvider, T

log = logging.getLogger(__name__)
R = TypeVar("R")
_COOLDOWN_ERRORS = (
    ProviderRateLimited,
    ProviderQuotaExceeded,
    ProviderAuthError,
    ProviderUnavailable,
)


class _Cooldown:
    def __init__(self, seconds: float, clock: Callable[[], float]) -> None:
        self._seconds = seconds
        self._clock = clock
        self._until = float("-inf")

    def active(self) -> bool:
        return self._clock() < self._until

    def start(self) -> None:
        self._until = self._clock() + self._seconds


async def _run(
    name: str,
    primary_name: str,
    cooldown: _Cooldown,
    call_primary: Callable[[], Awaitable[R]],
    call_fallback: Callable[[], Awaitable[R]],
) -> R:
    errors: list[ProviderError] = []
    if cooldown.active():
        log.info("primary in cooldown, using fallback", extra={"provider": primary_name})
    else:
        try:
            return await call_primary()
        except ProviderError as exc:
            errors.append(exc)
            if isinstance(exc, _COOLDOWN_ERRORS):
                cooldown.start()
            log.warning(
                "primary failed, trying fallback",
                extra={"provider": primary_name, "error": type(exc).__name__},
            )
    try:
        return await call_fallback()
    except ProviderError as exc:
        errors.append(exc)
        raise AllProvidersFailed(name, errors) from exc


class FallbackLLM:
    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        *,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary, self._fallback = primary, fallback
        self._cooldown = _Cooldown(cooldown_seconds, clock)
        self.name = f"{primary.name}+{fallback.name}"

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tier: ModelTier = ModelTier.STANDARD,
    ) -> T:
        def call(p: LLMProvider) -> Callable[[], Awaitable[T]]:
            return lambda: p.generate_structured(
                system=system, prompt=prompt, response_model=response_model, tier=tier
            )

        return await _run(
            self.name, self._primary.name, self._cooldown, call(self._primary), call(self._fallback)
        )


class FallbackSearch:
    def __init__(
        self,
        primary: SearchProvider,
        fallback: SearchProvider,
        *,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._primary, self._fallback = primary, fallback
        self._cooldown = _Cooldown(cooldown_seconds, clock)
        self.name = f"{primary.name}+{fallback.name}"

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        return await _run(
            self.name,
            self._primary.name,
            self._cooldown,
            lambda: self._primary.search(query, max_results=max_results),
            lambda: self._fallback.search(query, max_results=max_results),
        )