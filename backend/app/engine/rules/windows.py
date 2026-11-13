"""Freshness windows and evidence recency.

Responsibility: decide how old evidence may be (per claim volatility) and classify a piece of
evidence as recent, old or undated. Pure functions: the caller passes `now`; nothing here reads
the clock.
Dependencies: `app.schemas` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.schemas.labels import Volatility

# Evidence dated further in the future than this is treated as bad metadata (= undated).
FUTURE_TOLERANCE = timedelta(days=1)


@dataclass(frozen=True)
class FreshnessPolicy:
    """How many days evidence stays 'recent' for each volatility. Tunable in the M7 benchmark."""

    fast_days: int = 30
    slow_days: int = 365

    def __post_init__(self) -> None:
        if not (1 <= self.fast_days <= self.slow_days):
            raise ValueError("Require 1 <= fast_days <= slow_days.")


DEFAULT_POLICY = FreshnessPolicy()


class Recency(StrEnum):
    RECENT = "recent"
    OLD = "old"
    UNDATED = "undated"


def freshness_window_days(
    volatility: Volatility,
    policy: FreshnessPolicy = DEFAULT_POLICY,
    override: int | None = None,
) -> int | None:
    """Days evidence may be old and still count as recent. None = no time limit (static).

    `override` is a per-claim window (e.g. from the volatility classifier). It is ignored for
    static claims, which have no window by definition.
    """
    if volatility == Volatility.STATIC:
        return None
    if override is not None:
        if override < 1:
            raise ValueError("Window override must be >= 1 day.")
        return override
    return policy.fast_days if volatility == Volatility.FAST else policy.slow_days


def require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


def evidence_age_days(published_at: datetime | None, now: datetime) -> float | None:
    """Age in days, or None when unknown.

    None when there is no date, or the date is more than `FUTURE_TOLERANCE` in the future
    (bad metadata: we do not trust it). A date slightly in the future (clock skew) counts as 0.
    """
    require_aware(now, "now")
    if published_at is None:
        return None
    require_aware(published_at, "published_at")
    delta = now.astimezone(UTC) - published_at.astimezone(UTC)
    if delta < -FUTURE_TOLERANCE:
        return None
    return max(delta.total_seconds(), 0.0) / 86400.0


def classify_recency(
    published_at: datetime | None, now: datetime, window_days: int | None
) -> Recency:
    """RECENT if within the window; OLD if dated and older; UNDATED if unknown.

    With no window (static claims) everything is RECENT: age does not matter.
    """
    require_aware(now, "now")
    if window_days is None:
        return Recency.RECENT
    age = evidence_age_days(published_at, now)
    if age is None:
        return Recency.UNDATED
    return Recency.RECENT if age <= window_days else Recency.OLD