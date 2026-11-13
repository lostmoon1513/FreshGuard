"""Deterministic rules: source tiers, freshness windows, scoring and the decision table.

Everything here is a pure function. No LLM, no network, no clock, no I/O
(enforced by tests/unit/rules/test_purity.py).
"""

from app.engine.rules.decision import Decision, DecisionReason, decide_claim
from app.engine.rules.scoring import aggregate_answer
from app.engine.rules.source_tiers import classify_source, is_credible
from app.engine.rules.windows import (
    DEFAULT_POLICY,
    FreshnessPolicy,
    Recency,
    classify_recency,
    evidence_age_days,
    freshness_window_days,
)

__all__ = [
    "DEFAULT_POLICY",
    "Decision",
    "DecisionReason",
    "FreshnessPolicy",
    "Recency",
    "aggregate_answer",
    "classify_recency",
    "classify_source",
    "decide_claim",
    "evidence_age_days",
    "freshness_window_days",
    "is_credible",
]