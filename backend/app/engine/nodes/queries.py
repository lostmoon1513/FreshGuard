"""generate_queries: search queries per claim; one reformulation round at most."""

from __future__ import annotations

from app.engine.nodes import prompts
from app.engine.nodes.deps import Deps
from app.engine.nodes.llm_models import QueryBatch
from app.engine.nodes.state import ClaimWork, needs_search
from app.engine.nodes.text import clean_query
from app.engine.providers.errors import ProviderError
from app.engine.providers.models import ModelTier


def _merge(candidates: list[str], exclude: set[str], limit: int) -> tuple[str, ...]:
    out: list[str] = []
    seen = set(exclude)
    for raw in candidates:
        q = clean_query(raw)
        if q and q.lower() not in seen:
            seen.add(q.lower())
            out.append(q)
        if len(out) >= limit:
            break
    return tuple(out)


async def generate_queries(
    claims: list[ClaimWork], deps: Deps, *, reformulate: bool = False
) -> list[ClaimWork]:
    """Only searchable claims are touched. With `reformulate`, only claims that need it, and the
    previous queries are excluded. Falls back to the claim text itself if the LLM gives nothing."""
    limit = deps.limits.max_queries_per_claim
    targets = [
        i
        for i, c in enumerate(claims)
        if needs_search(c) and (c.attempts == 1 if reformulate else c.attempts == 0)
    ]
    if not targets:
        return claims
    proposals: dict[int, list[str]] = {}
    failed = False
    try:
        system = prompts.REFORMULATE_SYSTEM if reformulate else prompts.QUERY_SYSTEM
        batch = await deps.llm_call(
            system=system.replace("{max_queries}", str(limit)),
            prompt=prompts.query_prompt(
                [claims[i].text for i in targets],
                deps.clock(),
                [list(claims[i].queries) for i in targets] if reformulate else None,
            ),
            response_model=QueryBatch,
            tier=ModelTier.LIGHT,
        )
        for item in batch.items:
            if 0 <= item.index < len(targets):
                proposals.setdefault(targets[item.index], []).extend(item.queries)
    except ProviderError:
        failed = True
    out = list(claims)
    for i in targets:
        claim = claims[i]
        previous = {q.lower() for q in claim.queries}
        queries = _merge(proposals.get(i, []), previous if reformulate else set(), limit)
        updated = claim
        if not queries:
            fallback = clean_query(claim.text)
            queries = (
                (fallback,)
                if fallback and not (reformulate and fallback.lower() in previous)
                else ()
            )
            updated = updated.noted(
                "query generator unavailable; used claim text"
                if failed
                else "no queries; used claim text"
            )
        updated = updated.model_copy(update={"queries": queries, "attempts": claim.attempts + 1})
        out[i] = updated
    return out