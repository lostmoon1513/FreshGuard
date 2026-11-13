"""Deterministic evidence scoring and answer-level aggregation.

Responsibility: turn evidence into numbers (weights, side scores, confidence).
The *label* is never derived from these numbers; `decision.py` owns the label via a decision table.
Scores only express how strongly the evidence backs the label that was chosen.
Dependencies: `app.schemas`, `app.engine.rules.windows`.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.engine.rules.windows import evidence_age_days, require_aware
from app.schemas.evidence import Evidence
from app.schemas.labels import Label, SourceTier, worst_label

TIER_WEIGHT: dict[SourceTier, float] = {
    SourceTier.TIER_1: 0.9,
    SourceTier.TIER_2: 0.7,
    SourceTier.TIER_3: 0.35,
}
UNDATED_FACTOR = 0.5  # unknown age: worse than recent, better than known-old
OLD_FACTOR_FLOOR = 0.25  # weight multiplier for evidence far past the window
OLD_DECAY_SPAN = 2.0  # decays linearly from 1.0 at the window to the floor at (1+span)*window

POTENTIALLY_STALE_CAP = 0.5  # "needs a human look" is never a high-confidence verdict
STATIC_CONFIDENCE = 0.5  # static claims are not searched: deliberately not high


def recency_factor(age_days: float | None, window_days: int | None) -> float:
    """Multiplier in [OLD_FACTOR_FLOOR, 1]. Continuous at the window boundary."""
    if window_days is None:
        return 1.0
    if age_days is None:
        return UNDATED_FACTOR
    if age_days <= window_days:
        return 1.0
    overshoot = (age_days - window_days) / (window_days * OLD_DECAY_SPAN)
    return max(OLD_FACTOR_FLOOR, 1.0 - (1.0 - OLD_FACTOR_FLOOR) * min(1.0, overshoot))


def evidence_weight(evidence: Evidence, now: datetime, window_days: int | None) -> float:
    """Tier weight x recency factor, in (0, 0.9]."""
    require_aware(now, "now")
    age = evidence_age_days(evidence.published_at, now)
    return TIER_WEIGHT[evidence.tier] * recency_factor(age, window_days)


def noisy_or(weights: Iterable[float]) -> float:
    """Combine independent weights: 1 - prod(1 - w). Corroboration raises it, never past 1."""
    remaining = 1.0
    # Sorted so float rounding cannot depend on evidence order; rounded for stable storage.
    for w in sorted(min(max(w, 0.0), 1.0) for w in weights):
        remaining *= 1.0 - w
    return round(1.0 - remaining, 9)


def side_score(evidence: Iterable[Evidence], now: datetime, window_days: int | None) -> float:
    """Combined strength of one side (all supporting, or all contradicting) of the evidence."""
    return noisy_or(evidence_weight(e, now, window_days) for e in evidence)


def decisive_confidence(decisive: float, opposing: float) -> float:
    """Confidence in a FRESH/STALE verdict: own strength, discounted by opposing evidence."""
    return _clamp(decisive * (1.0 - opposing))


def potentially_stale_confidence(all_evidence_score: float) -> float:
    return _clamp(min(POTENTIALLY_STALE_CAP, all_evidence_score))


def aggregate_answer(claims: Iterable[tuple[Label, float]]) -> tuple[Label, float]:
    """Answer-level (label, confidence) from per-claim (label, confidence) pairs.

    Label = worst claim label (no claims = unverifiable, confidence 0).
    Confidence: FRESH needs every claim fresh, so it is the weakest claim's confidence (min).
    STALE / POTENTIALLY_STALE need just one claim, so it is the strongest claim *with that
    label* (max). UNVERIFIABLE is always 0.0: nothing trustworthy backs it.
    """
    items = list(claims)
    label = worst_label(lbl for lbl, _ in items)
    if label == Label.UNVERIFIABLE:
        return label, 0.0
    at_label = [_clamp(conf) for lbl, conf in items if lbl == label]
    return label, (min(at_label) if label == Label.FRESH else max(at_label))


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))