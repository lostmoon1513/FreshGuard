"""Enums shared across FreshGuard."""

from __future__ import annotations

from collections.abc import Iterable
from enum import IntEnum, StrEnum


class Label(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    POTENTIALLY_STALE = "potentially_stale"
    UNVERIFIABLE = "unverifiable"

    @property
    def severity(self) -> int:
        """Higher means worse. Order: stale > potentially_stale > unverifiable > fresh."""
        return _SEVERITY[self]


_SEVERITY: dict[Label, int] = {
    Label.STALE: 3,
    Label.POTENTIALLY_STALE: 2,
    Label.UNVERIFIABLE: 1,
    Label.FRESH: 0,
}


def worst_label(labels: Iterable[Label]) -> Label:
    """Answer-level label = the most severe claim-level label.

    No labels at all means nothing was checked, so the result is UNVERIFIABLE, never FRESH.
    """
    collected = list(labels)
    if not collected:
        return Label.UNVERIFIABLE
    return max(collected, key=lambda label: label.severity)


class Volatility(StrEnum):
    """How quickly a claim can go out of date."""

    STATIC = "static"
    SLOW = "slow"
    FAST = "fast"


class SourceTier(IntEnum):
    """Trust level of a source. 1 = official/primary, 2 = reputable secondary, 3 = other."""

    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


class Stance(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
