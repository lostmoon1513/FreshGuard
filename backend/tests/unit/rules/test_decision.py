"""Decision-table tests: every row, every boundary, with the reason code asserted."""

import pytest

from app.engine.rules.decision import DecisionReason as R
from app.engine.rules.decision import decide_claim
from app.engine.rules.windows import FreshnessPolicy
from app.schemas.labels import Label, SourceTier, Stance, Volatility
from tests.unit.rules._factory import NOW, ev

SUP, CON, NEU = Stance.SUPPORTS, Stance.CONTRADICTS, Stance.NEUTRAL
T1, T2, T3 = SourceTier.TIER_1, SourceTier.TIER_2, SourceTier.TIER_3
FAST, SLOW, STATIC = Volatility.FAST, Volatility.SLOW, Volatility.STATIC


def decide(vol, evidence, **kw):
    return decide_claim(vol, evidence, NOW, **kw)


# ---- rows 1-2: nothing verified -------------------------------------------------------------
def test_row1_static_without_evidence_is_fresh_but_low_confidence():
    d = decide(STATIC, [])
    assert (d.label, d.reason, d.window_days) == (Label.FRESH, R.STATIC_NOT_CHECKED, None)
    assert d.confidence == 0.5


@pytest.mark.parametrize("vol", [FAST, SLOW])
def test_row2_no_evidence_is_unverifiable(vol):
    d = decide(vol, [])
    assert (d.label, d.confidence, d.reason) == (Label.UNVERIFIABLE, 0.0, R.NO_VERIFIED_EVIDENCE)


@pytest.mark.parametrize(
    "evidence",
    [
        [ev(SUP, integrity_ok=None)],  # integrity check never ran
        [ev(SUP, integrity_ok=False)],  # fabricated/unmatched quote: discarded
        [ev(CON, integrity_ok=False)],
        [ev(NEU, integrity_ok=True)],  # neutral is not a verdict
        [ev(NEU, integrity_ok=None), ev(SUP, integrity_ok=False), ev(CON, integrity_ok=None)],
    ],
)
@pytest.mark.parametrize("vol", [FAST, SLOW])
def test_unverified_or_neutral_evidence_never_counts(vol, evidence):
    assert decide(vol, evidence).label == Label.UNVERIFIABLE


def test_static_with_only_unverified_evidence_still_static_fresh():
    d = decide(STATIC, [ev(CON, integrity_ok=False)])
    assert (d.label, d.reason) == (Label.FRESH, R.STATIC_NOT_CHECKED)


# ---- row 4: STALE ---------------------------------------------------------------------------
@pytest.mark.parametrize("tier", [T1, T2])
def test_row4_credible_recent_contradiction_is_stale(tier):
    d = decide(FAST, [ev(CON, tier, age_days=5)])
    assert (d.label, d.reason) == (Label.STALE, R.CREDIBLE_RECENT_CONTRADICTION)
    assert d.confidence == pytest.approx(0.9 if tier == T1 else 0.7)


def test_row4_corroboration_raises_confidence():
    one = decide(FAST, [ev(CON, T2, 5)])
    two = decide(FAST, [ev(CON, T2, 5), ev(CON, T1, 9)])
    assert two.label == Label.STALE and two.confidence > one.confidence


def test_row4_weak_support_lowers_confidence_but_keeps_stale():
    alone = decide(FAST, [ev(CON, T1, 5)])
    opposed = decide(FAST, [ev(CON, T1, 5), ev(SUP, T3, 5)])
    assert opposed.label == Label.STALE
    assert 0 < opposed.confidence < alone.confidence


def test_row4_old_support_does_not_block_stale():
    d = decide(FAST, [ev(CON, T2, 3), ev(SUP, T1, 400)])
    assert d.label == Label.STALE


# ---- row 5: FRESH ---------------------------------------------------------------------------
@pytest.mark.parametrize("tier", [T1, T2])
def test_row5_credible_recent_support_is_fresh(tier):
    d = decide(SLOW, [ev(SUP, tier, age_days=100)])
    assert (d.label, d.reason) == (Label.FRESH, R.CREDIBLE_RECENT_SUPPORT)


def test_row5_weak_contradiction_lowers_confidence_but_keeps_fresh():
    alone = decide(FAST, [ev(SUP, T1, 5)])
    opposed = decide(FAST, [ev(SUP, T1, 5), ev(CON, T3, 5)])
    assert opposed.label == Label.FRESH and opposed.confidence < alone.confidence


def test_row5_static_claim_with_credible_support_uses_evidence_not_default():
    d = decide(STATIC, [ev(SUP, T1, age_days=5000)])
    assert d.reason == R.CREDIBLE_RECENT_SUPPORT and d.confidence == pytest.approx(0.9)


def test_static_claim_with_credible_contradiction_is_stale_regardless_of_age():
    assert decide(STATIC, [ev(CON, T1, age_days=5000)]).label == Label.STALE


# ---- row 3: credible conflict ---------------------------------------------------------------
@pytest.mark.parametrize(("t_sup", "t_con"), [(T1, T1), (T1, T2), (T2, T1), (T2, T2)])
def test_row3_credible_recent_conflict_is_potentially_stale(t_sup, t_con):
    d = decide(FAST, [ev(SUP, t_sup, 3), ev(CON, t_con, 4)])
    assert (d.label, d.reason) == (Label.POTENTIALLY_STALE, R.CREDIBLE_SOURCES_CONFLICT)
    assert 0 < d.confidence <= 0.5


# ---- row 6: weak only -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "evidence",
    [
        [ev(SUP, T3, 1)],  # low-tier
        [ev(CON, T3, 1)],
        [ev(SUP, T1, 400)],  # old (fast window is 30)
        [ev(CON, T1, 400)],
        [ev(SUP, T1, None)],  # undated
        [ev(CON, T2, None)],
        [ev(SUP, T1, 400), ev(CON, T3, 1)],  # weak conflict
        [ev(SUP, T3, 1), ev(CON, T3, 1)],
    ],
)
def test_row6_only_weak_evidence_is_potentially_stale(evidence):
    d = decide(FAST, evidence)
    assert (d.label, d.reason) == (Label.POTENTIALLY_STALE, R.ONLY_WEAK_EVIDENCE)
    assert 0 < d.confidence <= 0.5


def test_a_strong_item_among_weak_ones_is_enough():
    assert decide(FAST, [ev(SUP, T3, 1), ev(SUP, T1, None), ev(SUP, T2, 2)]).label == Label.FRESH


# ---- window boundaries ----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("vol", "window"),
    [(FAST, 30), (SLOW, 365)],
)
def test_window_boundary_is_inclusive(vol, window):
    assert decide(vol, [ev(SUP, T1, window)]).label == Label.FRESH
    assert decide(vol, [ev(SUP, T1, window + 0.5)]).label == Label.POTENTIALLY_STALE


def test_same_evidence_different_volatility():
    e = [ev(SUP, T1, 100)]
    assert decide(FAST, e).label == Label.POTENTIALLY_STALE
    assert decide(SLOW, e).label == Label.FRESH


def test_custom_policy_and_override_change_the_boundary():
    e = [ev(SUP, T1, 20)]
    assert decide(FAST, e).label == Label.FRESH
    assert decide(FAST, e, policy=FreshnessPolicy(fast_days=7, slow_days=30)).label == (
        Label.POTENTIALLY_STALE
    )
    assert decide(FAST, e, window_days_override=10).label == Label.POTENTIALLY_STALE
    assert decide(FAST, e, window_days_override=10).window_days == 10


def test_future_dated_evidence_cannot_look_recent():
    from datetime import timedelta

    e = ev(SUP, T1, age_days=-40)  # published 40 days in the future: bad metadata
    assert e.published_at == NOW + timedelta(days=40)
    assert decide(FAST, [e]).label == Label.POTENTIALLY_STALE


def test_naive_now_is_rejected():
    from datetime import datetime

    with pytest.raises(ValueError):
        decide_claim(FAST, [], datetime(2026, 1, 1))


def test_explanation_is_nonempty_and_deterministic():
    e = [ev(CON, T1, 2), ev(SUP, T3, 2)]
    d1, d2 = decide(FAST, e), decide(FAST, e)
    assert d1 == d2 and d1.explanation