"""Exhaustive / property-style checks of the decision table.

Enumerates every evidence "kind" (stance x tier x recency x integrity) and checks invariants on
all single items, all ordered pairs, and a seeded random sample of larger sets.
"""

import itertools
import random

import pytest

from app.engine.rules.decision import decide_claim
from app.schemas.claim import ClaimVerdict
from app.schemas.labels import Label, SourceTier, Stance, Volatility
from tests.unit.rules._factory import NOW, ev

# recent for both windows, recent for fast, old for fast only, old for both, undated
AGES = [1, 29, 31, 400, None]
KINDS = [
    (stance, tier, age, integrity)
    for stance in Stance
    for tier in SourceTier
    for age in AGES
    for integrity in (True, False, None)
]
KIND_EVIDENCE = [ev(s, t, a, i) for s, t, a, i in KINDS]
NON_STATIC = [Volatility.FAST, Volatility.SLOW]


def _verified(e):
    return e.integrity_ok is True and e.stance != Stance.NEUTRAL


def _all_sets():
    yield ()
    for e in KIND_EVIDENCE:
        yield (e,)
    yield from itertools.product(KIND_EVIDENCE, repeat=2)
    rng = random.Random(1234)
    for _ in range(4000):
        yield tuple(rng.choices(KIND_EVIDENCE, k=rng.randint(3, 6)))


def test_kind_space_size():
    assert len(KINDS) == 3 * 3 * 5 * 3 == 135


@pytest.mark.parametrize("vol", list(Volatility))
def test_invariants_over_all_evidence_sets(vol):
    checked = 0
    for evidence in _all_sets():
        d = decide_claim(vol, evidence, NOW)
        checked += 1

        # Valid label, confidence in range, deterministic.
        assert d.label in set(Label)
        assert 0.0 <= d.confidence <= 1.0
        assert d == decide_claim(vol, evidence, NOW)

        # Order never matters.
        assert d == decide_claim(vol, tuple(reversed(evidence)), NOW)

        verified = [e for e in evidence if _verified(e)]
        if not verified:
            # Never guess: nothing verified -> unverifiable (static claims are not searched).
            expected = Label.FRESH if vol == Volatility.STATIC else Label.UNVERIFIABLE
            assert d.label == expected
        else:
            assert d.label != Label.UNVERIFIABLE  # verified evidence always yields a verdict

        # The schema guard ("never invent results") accepts every decision we produce.
        ClaimVerdict(
            text="claim",
            volatility=vol,
            label=d.label,
            freshness_window_days=d.window_days,
            evidence=list(evidence),
        )

        # Ignorable evidence is truly ignorable: dropping it never changes the decision.
        kept = tuple(e for e in evidence if _verified(e))
        assert decide_claim(vol, kept, NOW) == d
    assert checked > 12_000


@pytest.mark.parametrize("vol", NON_STATIC)
def test_stale_and_fresh_always_have_a_credible_recent_verified_source(vol):
    for evidence in _all_sets():
        d = decide_claim(vol, evidence, NOW)
        wanted = {Label.STALE: Stance.CONTRADICTS, Label.FRESH: Stance.SUPPORTS}.get(d.label)
        if wanted is None:
            continue
        window = d.window_days
        assert any(
            e.integrity_ok is True
            and e.stance == wanted
            and e.tier <= SourceTier.TIER_2
            and e.published_at is not None
            and (NOW - e.published_at).days <= window
            for e in evidence
        )


@pytest.mark.parametrize("vol", NON_STATIC)
def test_adding_a_neutral_item_never_changes_the_decision(vol):
    neutral = ev(Stance.NEUTRAL, SourceTier.TIER_1, 1, True)
    for evidence in _all_sets():
        assert decide_claim(vol, evidence + (neutral,), NOW) == decide_claim(vol, evidence, NOW)


@pytest.mark.parametrize("vol", NON_STATIC)
def test_adding_support_never_turns_a_non_stale_verdict_into_stale(vol):
    """Evidence only moves a verdict in the direction it points."""
    extra = ev(Stance.SUPPORTS, SourceTier.TIER_1, 1, True)
    for evidence in _all_sets():
        before = decide_claim(vol, evidence, NOW).label
        after = decide_claim(vol, evidence + (extra,), NOW).label
        if before != Label.STALE:
            assert after != Label.STALE