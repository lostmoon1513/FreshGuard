"""decide: apply the deterministic decision table and build the claim verdict."""

from __future__ import annotations

from app.engine.nodes.deps import Deps
from app.engine.nodes.state import ClaimWork
from app.engine.rules.decision import decide_claim
from app.schemas.claim import ClaimVerdict
from app.schemas.labels import Stance


def decide(claim: ClaimWork, deps: Deps) -> ClaimWork:
    decision = decide_claim(
        claim.volatility,
        claim.evidence,
        deps.clock(),
        window_days_override=claim.window_days,
        policy=deps.policy,
    )
    kept = [e for e in claim.evidence if e.stance == Stance.NEUTRAL or e.integrity_ok is True]
    verdict = ClaimVerdict(
        text=claim.text,
        volatility=claim.volatility,
        label=decision.label,
        reasoning=decision.explanation,
        freshness_window_days=decision.window_days,
        evidence=kept,
    )
    return claim.model_copy(update={"decision": decision, "verdict": verdict})