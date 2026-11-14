"""The claim-level decision table. The ONLY place a claim's label is decided.

Responsibility: (volatility, evidence, now) -> Decision(label, confidence, reason, explanation).
Pure and deterministic; no LLM, no network, no clock (the caller passes `now`).
Dependencies: `app.schemas`, other `app.engine.rules` modules.

Terms
  verified    stance is supports/contradicts AND `integrity_ok is True` (quote was a verbatim
              substring of a fetched page). Anything else is ignored: never trusted, never guessed.
  strong      verified AND credible source (tier 1-2) AND recent (inside the freshness window).

Table (first matching row wins; see docs/RULES.md)
  1  no verified evidence, static claim         -> FRESH              (not searched)
  2  no verified evidence                       -> UNVERIFIABLE
  3  strong support AND strong contradiction    -> POTENTIALLY_STALE  (credible sources conflict)
  4  strong contradiction                       -> STALE
  5  strong support, nothing contradicts       -> FRESH
  5b strong support but any verified contradiction -> POTENTIALLY_STALE (support contested)
  6  only weak evidence (tier 3, old, undated)  -> POTENTIALLY_STALE

Rows 4 and 5 discount confidence by any opposing (weak) evidence but keep the label.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.engine.rules.scoring import (
    STATIC_CONFIDENCE,
    decisive_confidence,
    noisy_or,
    potentially_stale_confidence,
    side_score,
)
from app.engine.rules.source_tiers import is_credible
from app.engine.rules.windows import (
    DEFAULT_POLICY,
    FreshnessPolicy,
    Recency,
    classify_recency,
    freshness_window_days,
    require_aware,
)
from app.schemas.evidence import Evidence
from app.schemas.labels import Label, Stance, Volatility


class DecisionReason(StrEnum):
    STATIC_NOT_CHECKED = "static_not_checked"
    NO_VERIFIED_EVIDENCE = "no_verified_evidence"
    CREDIBLE_SOURCES_CONFLICT = "credible_sources_conflict"
    CREDIBLE_RECENT_CONTRADICTION = "credible_recent_contradiction"
    CREDIBLE_RECENT_SUPPORT = "credible_recent_support"
    SUPPORT_CONTESTED = "support_contested"
    ONLY_WEAK_EVIDENCE = "only_weak_evidence"


@dataclass(frozen=True)
class Decision:
    label: Label
    confidence: float
    reason: DecisionReason
    explanation: str
    window_days: int | None


def _is_strong(e: Evidence, now: datetime, window_days: int | None) -> bool:
    recency = classify_recency(e.published_at, now, window_days)
    return is_credible(e.tier) and recency == Recency.RECENT


def decide_claim(
    volatility: Volatility,
    evidence: Sequence[Evidence],
    now: datetime,
    *,
    window_days_override: int | None = None,
    policy: FreshnessPolicy = DEFAULT_POLICY,
) -> Decision:
    """Decide one claim's label from its (already integrity-checked) evidence."""
    require_aware(now, "now")
    window = freshness_window_days(volatility, policy, window_days_override)

    supports = [e for e in evidence if e.integrity_ok is True and e.stance == Stance.SUPPORTS]
    contradicts = [e for e in evidence if e.integrity_ok is True and e.stance == Stance.CONTRADICTS]

    # Rows 1-2: nothing verified.
    if not supports and not contradicts:
        if volatility == Volatility.STATIC:
            return Decision(
                Label.FRESH,
                STATIC_CONFIDENCE,
                DecisionReason.STATIC_NOT_CHECKED,
                "Static claim: not searched, treated as not time-sensitive.",
                window,
            )
        return Decision(
            Label.UNVERIFIABLE,
            0.0,
            DecisionReason.NO_VERIFIED_EVIDENCE,
            "No verified supporting or contradicting evidence was found.",
            window,
        )

    strong_support = any(_is_strong(e, now, window) for e in supports)
    strong_contra = any(_is_strong(e, now, window) for e in contradicts)
    support_score = side_score(supports, now, window)
    contra_score = side_score(contradicts, now, window)
    counts = f"{len(supports)} supporting, {len(contradicts)} contradicting verified source(s)"

    # Row 3: credible, recent sources disagree.
    if strong_support and strong_contra:
        return Decision(
            Label.POTENTIALLY_STALE,
            potentially_stale_confidence(noisy_or([support_score, contra_score])),
            DecisionReason.CREDIBLE_SOURCES_CONFLICT,
            f"Credible, recent sources disagree ({counts}); needs a human look.",
            window,
        )
    # Row 4.
    if strong_contra:
        return Decision(
            Label.STALE,
            decisive_confidence(contra_score, support_score),
            DecisionReason.CREDIBLE_RECENT_CONTRADICTION,
            f"A credible, recent source contradicts the claim ({counts}).",
            window,
        )
    # Row 5b: never "fresh" while any verified source (even a weak one) contradicts the claim.
    if strong_support and contradicts:
        return Decision(
            Label.POTENTIALLY_STALE,
            potentially_stale_confidence(noisy_or([support_score, contra_score])),
            DecisionReason.SUPPORT_CONTESTED,
            f"A credible source supports the claim but another source contradicts it "
            f"({counts}); needs a human look.",
            window,
        )
    # Row 5.
    if strong_support:
        return Decision(
            Label.FRESH,
            decisive_confidence(support_score, contra_score),
            DecisionReason.CREDIBLE_RECENT_SUPPORT,
            f"A credible, recent source supports the claim ({counts}).",
            window,
        )
    # Row 6.
    return Decision(
        Label.POTENTIALLY_STALE,
        potentially_stale_confidence(noisy_or([support_score, contra_score])),
        DecisionReason.ONLY_WEAK_EVIDENCE,
        f"Only weak evidence (low-tier, old or undated sources) ({counts}); needs a human look.",
        window,
    )