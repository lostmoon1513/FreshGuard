"""validate_sources: turn raw hits into trusted `Source`s (tiered, dated, with page text)."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime

from app.engine.nodes.deps import Deps
from app.engine.nodes.state import ClaimWork, Source, needs_search
from app.engine.providers.errors import FetchError
from app.engine.providers.models import SearchHit
from app.engine.rules.source_tiers import classify_source
from app.schemas.evidence import Document
from app.schemas.labels import SourceTier, Volatility

log = logging.getLogger(__name__)


_URL_DATE = re.compile(r"/((?:19|20)\d{2})/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])(?:/|$)")


def url_date(url: str) -> datetime | None:
    """Publication date encoded in a news-style path (/2021/11/30/...), else None.

    Last-resort fallback, used only when neither the page nor the search provider gave a date.
    The pattern is strict (year/month/day directory segments) to avoid reading ids as dates.
    """
    match = _URL_DATE.search(url)
    if not match:
        return None
    try:
        return datetime(*(int(g) for g in match.groups()), tzinfo=UTC)
    except ValueError:
        return None


def _with_url_date(doc: Document) -> Document:
    if doc.published_at is not None:
        return doc
    fallback = url_date(str(doc.url))
    return doc.model_copy(update={"published_at": fallback}) if fallback else doc


def _rank_key(item: tuple[SearchHit, SourceTier]) -> tuple[int, int, int]:
    hit, tier = item
    return (int(tier), 0 if (hit.content or "").strip() else 1, 0 if hit.published_at else 1)


def _from_hit(hit: SearchHit, now) -> Document | None:
    text = (hit.content or "").strip()
    if not text:
        return None
    return Document(
        url=hit.url,
        title=hit.title or None,
        text=text,
        published_at=hit.published_at,
        fetched_at=hit.retrieved_at or now,
    )


async def _fetch(hit: SearchHit, deps: Deps) -> Document | None:
    assert deps.fetcher is not None
    try:
        async with deps.fetch_slots:
            return await deps.fetcher.fetch(str(hit.url))
    except FetchError as exc:
        log.info("Page fetch failed (%s): %s", type(exc).__name__, hit.url)
        return None


async def validate_sources(claim: ClaimWork, deps: Deps) -> ClaimWork:
    """Rank hits (tier, has text, dated), fetch pages when worthwhile, drop what we cannot quote.

    A page is fetched only for credible (tier 1-2) hits that have no page text, or are undated
    on a time-sensitive claim. Snippet-only hits that cannot be fetched are dropped: a snippet is
    too thin to quote safely. A page's own publish date beats the search provider's date.
    """
    if not needs_search(claim):
        return claim
    limits = deps.limits
    ranked = sorted(((h, classify_source(str(h.url))) for h in claim.hits), key=_rank_key)[
        : limits.max_candidates
    ]
    now = deps.clock()
    fetch_budget = limits.max_fetches_per_claim if deps.fetcher else 0

    plans: list[tuple[SearchHit, SourceTier, bool]] = []
    for hit, tier in ranked:
        has_text = bool((hit.content or "").strip())
        wants = tier <= SourceTier.TIER_2 and (
            not has_text or (hit.published_at is None and claim.volatility != Volatility.STATIC)
        )
        if wants and fetch_budget > 0:
            fetch_budget -= 1
            plans.append((hit, tier, True))
        else:
            plans.append((hit, tier, False))

    fetched = await asyncio.gather(*(_fetch(h, deps) if go else _none() for h, _, go in plans))
    sources: list[Source] = []
    for (hit, tier, _go), page in zip(plans, fetched, strict=True):
        if page is not None:
            doc = page
            if doc.published_at is None and hit.published_at is not None:
                doc = doc.model_copy(update={"published_at": hit.published_at})
            sources.append(
                Source(
                    document=_with_url_date(_with_credible_modified(doc, tier)),
                    tier=tier,
                    from_fetch=True,
                )
            )
            continue
        doc = _from_hit(hit, now)
        if doc is not None:
            sources.append(Source(document=_with_url_date(doc), tier=tier))
    sources.sort(key=lambda s: int(s.tier))
    kept = tuple(sources[: limits.max_sources_per_claim])
    return claim.model_copy(update={"sources": kept})


def _with_credible_modified(doc: Document, tier: SourceTier) -> Document:
    """D38: a tier 1-2 page's 'last updated' date counts as its recency when later than its
    publish date (or when it has none). Tier 3 never gets this: undated stays weak."""
    if tier > SourceTier.TIER_2 or doc.modified_at is None:
        return doc
    if doc.published_at is not None and doc.modified_at <= doc.published_at:
        return doc
    if doc.modified_at > doc.fetched_at:
        return doc  # a date in the future is not evidence of anything
    return doc.model_copy(update={"published_at": doc.modified_at})


async def _none() -> None:
    return None