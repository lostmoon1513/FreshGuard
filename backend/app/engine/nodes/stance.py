"""compare_stance: the LLM's only judgement call - does each source support/contradict the claim?"""

from __future__ import annotations

from app.engine.nodes import prompts
from app.engine.nodes.deps import Deps
from app.engine.nodes.llm_models import StanceBatch
from app.engine.nodes.state import ClaimWork
from app.engine.nodes.text import select_passage, shares_content_token
from app.engine.providers.errors import ProviderError
from app.engine.providers.models import ModelTier
from app.schemas.evidence import Evidence
from app.schemas.labels import Stance


async def compare_stance(claim: ClaimWork, deps: Deps) -> ClaimWork:
    """One LLM call per claim over all its sources. Safety rules applied in code:
    quote-less supports/contradicts become neutral; off-topic passages become neutral;
    one verdict per source. `integrity_ok` stays None until the integrity node runs."""
    if not claim.sources:
        return claim
    passages = [
        select_passage(s.document.text, claim.text, deps.limits.passage_chars)
        for s in claim.sources
    ]
    listing = [
        (
            str(s.document.url),
            s.document.title,
            s.document.published_at.date().isoformat() if s.document.published_at else None,
            passage,
        )
        for s, passage in zip(claim.sources, passages, strict=True)
    ]
    try:
        batch = await deps.llm_call(
            system=prompts.STANCE_SYSTEM,
            prompt=prompts.stance_prompt(claim.text, listing, deps.clock()),
            response_model=StanceBatch,
            tier=ModelTier.STANDARD,
        )
    except ProviderError:
        return claim.model_copy(update={"provider_failed": True}).noted("stance model unavailable")

    chosen: dict[int, tuple[Stance, str | None]] = {}
    for item in batch.items:
        if 1 <= item.source <= len(claim.sources) and item.source not in chosen:
            chosen[item.source] = (item.stance, (item.quote or "").strip() or None)

    evidence: list[Evidence] = []
    for n, (source, passage) in enumerate(zip(claim.sources, passages, strict=True), start=1):
        stance, quote = chosen.get(n, (Stance.NEUTRAL, None))
        if stance != Stance.NEUTRAL and (
            quote is None or not shares_content_token(claim.text, passage)
        ):
            stance, quote = Stance.NEUTRAL, None
        evidence.append(
            Evidence(
                url=source.document.url,
                tier=source.tier,
                published_at=source.document.published_at,
                fetched_at=source.document.fetched_at,
                stance=stance,
                quoted_span=quote if stance != Stance.NEUTRAL else None,
            )
        )
    return claim.model_copy(update={"evidence": tuple(evidence), "provider_failed": False})