"""suggest_correction: one grounded replacement sentence, only for STALE claims."""

from __future__ import annotations

from app.engine.nodes import prompts
from app.engine.nodes.deps import Deps
from app.engine.nodes.llm_models import CorrectionOut
from app.engine.nodes.state import ClaimWork
from app.engine.nodes.text import capitalised_terms, numbers_in
from app.engine.providers.errors import ProviderError
from app.engine.providers.models import ModelTier
from app.schemas.labels import Label, Stance

MAX_QUOTES = 3


async def suggest_correction(claim: ClaimWork, deps: Deps) -> ClaimWork:
    """The sentence is accepted only if every number and name in it appears in the cited quote or
    the original claim. Otherwise no correction is offered (honest > clever)."""
    if claim.verdict is None or claim.verdict.label != Label.STALE:
        return claim
    contra = [
        e for e in claim.evidence if e.stance == Stance.CONTRADICTS and e.integrity_ok is True
    ][:MAX_QUOTES]
    if not contra:
        return claim
    quotes = [
        (
            str(e.url),
            e.published_at.date().isoformat() if e.published_at else None,
            e.quoted_span or "",
        )
        for e in contra
    ]
    try:
        out = await deps.llm_call(
            system=prompts.CORRECTION_SYSTEM,
            prompt=prompts.correction_prompt(claim.text, quotes, deps.clock()),
            response_model=CorrectionOut,
            tier=ModelTier.STANDARD,
        )
    except ProviderError:
        return claim.noted("correction model unavailable")
    text = " ".join((out.correction or "").split())
    if not text or out.evidence is None or not 1 <= out.evidence <= len(quotes):
        return claim
    if len(text) > deps.limits.max_correction_chars:
        return claim.noted("correction rejected: too long")
    cited = quotes[out.evidence - 1][2]
    allowed = f"{cited} {claim.text}"
    if not numbers_in(text) <= numbers_in(allowed):
        return claim.noted("correction rejected: ungrounded number")
    if not capitalised_terms(text) <= capitalised_terms(allowed) | capitalised_terms(
        f"x {allowed}"
    ):
        return claim.noted("correction rejected: ungrounded name")
    return claim.model_copy(update={"correction": text})