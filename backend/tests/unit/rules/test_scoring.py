import pytest

from app.engine.rules.scoring import (
    OLD_FACTOR_FLOOR,
    POTENTIALLY_STALE_CAP,
    TIER_WEIGHT,
    UNDATED_FACTOR,
    aggregate_answer,
    decisive_confidence,
    evidence_weight,
    noisy_or,
    potentially_stale_confidence,
    recency_factor,
    side_score,
)
from app.schemas.labels import Label, SourceTier
from tests.unit.rules._factory import NOW, ev

F, S, P, U = Label.FRESH, Label.STALE, Label.POTENTIALLY_STALE, Label.UNVERIFIABLE


def test_tier_weights_are_ordered_and_below_one():
    w = TIER_WEIGHT
    assert 0 < w[SourceTier.TIER_3] < w[SourceTier.TIER_2] < w[SourceTier.TIER_1] < 1


def test_recency_factor_shape():
    assert recency_factor(5, None) == 1.0
    assert recency_factor(None, None) == 1.0
    assert recency_factor(None, 30) == UNDATED_FACTOR
    assert recency_factor(0, 30) == 1.0
    assert recency_factor(30, 30) == 1.0
    assert recency_factor(30.0001, 30) == pytest.approx(1.0, abs=1e-3)  # continuous
    assert recency_factor(60, 30) == pytest.approx((1 + OLD_FACTOR_FLOOR) / 2)  # halfway
    assert recency_factor(90, 30) == pytest.approx(OLD_FACTOR_FLOOR)
    assert recency_factor(10_000, 30) == OLD_FACTOR_FLOOR


def test_recency_factor_is_monotonic_non_increasing():
    ages = [0, 10, 30, 31, 45, 60, 89, 90, 500]
    factors = [recency_factor(a, 30) for a in ages]
    assert factors == sorted(factors, reverse=True)
    assert all(OLD_FACTOR_FLOOR <= f <= 1 for f in factors)


def test_known_old_is_never_better_than_undated_far_past_window():
    assert recency_factor(1000, 30) < UNDATED_FACTOR


def test_evidence_weight():
    assert evidence_weight(ev(tier=SourceTier.TIER_1, age_days=1), NOW, 30) == 0.9
    undated_t2 = ev(tier=SourceTier.TIER_2, age_days=None)
    assert evidence_weight(undated_t2, NOW, 30) == pytest.approx(0.35)
    assert evidence_weight(ev(tier=SourceTier.TIER_3, age_days=1), NOW, None) == 0.35


def test_noisy_or():
    assert noisy_or([]) == 0.0
    assert noisy_or([0.5]) == 0.5
    assert noisy_or([0.5, 0.5]) == 0.75
    assert noisy_or([0.9, 0.9, 0.9]) < 1.0
    assert noisy_or([1.5]) == 1.0  # clamps out-of-range inputs
    assert noisy_or([-1]) == 0.0


def test_corroboration_raises_side_score_but_order_does_not_matter():
    a, b = ev(tier=SourceTier.TIER_2), ev(tier=SourceTier.TIER_1)
    assert side_score([a], NOW, 30) < side_score([a, b], NOW, 30)
    assert side_score([a, b], NOW, 30) == side_score([b, a], NOW, 30)
    assert side_score([], NOW, 30) == 0.0


def test_decisive_confidence_is_discounted_by_opposition():
    assert decisive_confidence(0.8, 0.0) == 0.8
    assert decisive_confidence(0.8, 0.5) == pytest.approx(0.4)
    assert decisive_confidence(0.8, 1.0) == 0.0
    assert 0 <= decisive_confidence(5, -3) <= 1


def test_potentially_stale_confidence_is_capped():
    assert potentially_stale_confidence(0.99) == POTENTIALLY_STALE_CAP
    assert potentially_stale_confidence(0.2) == 0.2
    assert potentially_stale_confidence(0.0) == 0.0


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ([], (U, 0.0)),
        ([(U, 0.0)], (U, 0.0)),
        ([(F, 0.9), (F, 0.6)], (F, 0.6)),  # fresh: weakest link
        ([(S, 0.6), (S, 0.9), (F, 0.99)], (S, 0.9)),  # stale: strongest stale claim
        ([(P, 0.3), (P, 0.5), (F, 0.9)], (P, 0.5)),
        ([(F, 0.9), (U, 0.0)], (U, 0.0)),  # unverifiable beats fresh
        ([(U, 0.0), (P, 0.4)], (P, 0.4)),
        ([(P, 0.4), (S, 0.7), (U, 0.0), (F, 0.9)], (S, 0.7)),
    ],
)
def test_aggregate_answer(claims, expected):
    assert aggregate_answer(claims) == expected


def test_aggregate_answer_label_matches_worst_label_rule():
    from app.schemas.labels import worst_label

    claims = [(P, 0.4), (F, 0.9)]
    assert aggregate_answer(claims)[0] == worst_label(lbl for lbl, _ in claims)