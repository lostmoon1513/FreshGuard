"""Shared helper: turn raw provider result dicts into validated, de-duplicated SearchHits."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.engine.providers.models import SearchHit, truncate_text


def build_hits(
    provider: str,
    items: Iterable[Any],
    *,
    url_key: str,
    snippet_key: str,
    content_key: str | None,
    date_of: Callable[[dict[str, Any]], datetime | None],
    retrieved_at: datetime,
    max_results: int,
) -> list[SearchHit]:
    """Skip anything malformed, without a URL, or without any text. Never invent fields."""
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = item.get(snippet_key)
        content = item.get(content_key) if content_key else None
        snippet = snippet if isinstance(snippet, str) else ""
        content = content if isinstance(content, str) and content.strip() else None
        title = item.get("title")
        try:
            hit = SearchHit(
                url=item.get(url_key) or "",
                title=title if isinstance(title, str) else "",
                snippet=truncate_text(snippet),
                content=truncate_text(content) if content else None,
                published_at=date_of(item),
                retrieved_at=retrieved_at,
                provider=provider,
            )
        except ValidationError:
            continue
        if not hit.text or str(hit.url) in seen:
            continue
        seen.add(str(hit.url))
        hits.append(hit)
        if len(hits) >= max_results:
            break
    return hits