"""retrieve_evidence: run a claim's queries against the search provider and collect hits."""

from __future__ import annotations

import asyncio

from app.engine.nodes.deps import Deps
from app.engine.nodes.state import ClaimWork, needs_search
from app.engine.nodes.text import normalize_url
from app.engine.providers.errors import ProviderError
from app.engine.providers.models import SearchHit


async def _one(query: str, deps: Deps) -> list[SearchHit] | ProviderError:
    try:
        async with deps.search_slots:
            return await deps.search.search(query, max_results=deps.limits.results_per_query)
    except ProviderError as exc:
        return exc


async def retrieve_evidence(claim: ClaimWork, deps: Deps) -> ClaimWork:
    """Search every current query. Partial failure is fine; only if EVERY query failed with a
    provider error is the claim marked `provider_failed` (an outage, not 'no evidence')."""
    if not needs_search(claim) or not claim.queries:
        return claim
    results = await asyncio.gather(*(_one(q, deps) for q in claim.queries))
    errors = [r for r in results if isinstance(r, ProviderError)]
    hits_by_url = {normalize_url(str(h.url)): h for h in claim.hits}
    for r in results:
        if isinstance(r, ProviderError):
            continue
        for hit in r:
            key = normalize_url(str(hit.url))
            old = hits_by_url.get(key)
            if old is None or len(hit.text) > len(old.text):
                hits_by_url[key] = hit
    hits = tuple(list(hits_by_url.values())[: deps.limits.max_hits_per_claim])
    failed = len(errors) == len(results) and not hits
    updated = claim.model_copy(update={"hits": hits, "provider_failed": failed})
    if errors:
        updated = updated.noted(f"{len(errors)} of {len(results)} searches failed")
    return updated