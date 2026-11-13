"""Test helpers: build evidence and timestamps concisely."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.evidence import Evidence
from app.schemas.labels import SourceTier, Stance

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def days_ago(n: float) -> datetime:
    return NOW - timedelta(days=n)


def ev(
    stance: Stance = Stance.SUPPORTS,
    tier: SourceTier = SourceTier.TIER_1,
    age_days: float | None = 1,
    integrity_ok: bool | None = True,
    url: str = "https://example.org/page",
) -> Evidence:
    """Evidence `age_days` old (None = undated). Quote is added for non-neutral stances."""
    return Evidence(
        url=url,
        tier=tier,
        published_at=None if age_days is None else days_ago(age_days),
        fetched_at=NOW,
        stance=stance,
        quoted_span=None if stance == Stance.NEUTRAL else "a verbatim quote",
        integrity_ok=integrity_ok,
    )