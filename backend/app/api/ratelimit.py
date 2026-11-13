"""A small in-memory sliding-window rate limiter (per process; fine for a single-instance demo)."""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window must be positive")
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> int | None:
        """Record a request. Returns None if allowed, else seconds to wait (>= 1)."""
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return max(1, math.ceil(self._window - (now - hits[0])))
        hits.append(now)
        if len(self._hits) > 10_000:  # bound memory: drop idle keys
            for k in [k for k, v in self._hits.items() if not v]:
                del self._hits[k]
        return None