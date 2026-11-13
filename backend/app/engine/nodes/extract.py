"""extract_claims: answer text -> grounded atomic claims."""

from __future__ import annotations

import logging

from app.engine.nodes import prompts
from app.engine.nodes.deps import Deps
from app.engine.nodes.llm_models import ExtractedClaims
from app.engine.nodes.state import ClaimWork
from app.engine.nodes.text import contains_verbatim
from app.engine.providers.models import ModelTier

log = logging.getLogger(__name__)


async def extract_claims(question: str, answer: str, deps: Deps) -> list[ClaimWork]:
    """Ask the LLM for claims, then keep only those whose `answer_span` really occurs in the answer.

    Raises ProviderError if the LLM is unavailable (the caller turns that into a FAILED result).
    """
    limits = deps.limits
    out = await deps.llm_call(
        system=prompts.EXTRACT_SYSTEM.replace("{max_claims}", str(limits.max_claims)),
        prompt=prompts.extract_prompt(question, answer, deps.clock()),
        response_model=ExtractedClaims,
        tier=ModelTier.STANDARD,
    )
    claims: list[ClaimWork] = []
    seen: set[str] = set()
    for item in out.claims:
        text = " ".join(item.text.split())[: limits.max_claim_chars].strip()
        span = " ".join(item.answer_span.split())
        key = text.lower()
        if not text or key in seen:
            continue
        if not span or not contains_verbatim(answer, span):
            log.info("Dropped claim without a grounded answer span.")
            continue
        seen.add(key)
        claims.append(ClaimWork(text=text, answer_span=span))
        if len(claims) >= limits.max_claims:
            break
    return claims