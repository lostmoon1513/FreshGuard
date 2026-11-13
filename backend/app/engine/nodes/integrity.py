"""check_quote_integrity: every quote must be a verbatim substring of the page we hold."""

from __future__ import annotations

import logging

from app.engine.nodes.state import ClaimWork
from app.engine.nodes.text import contains_verbatim
from app.schemas.labels import Stance

log = logging.getLogger(__name__)

MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 600
MIN_QUOTE_WORDS = 4


def quote_is_acceptable(quote: str) -> bool:
    q = quote.strip()
    return (
        MIN_QUOTE_CHARS <= len(q) <= MAX_QUOTE_CHARS
        and len(q.split()) >= MIN_QUOTE_WORDS
        and "..." not in q
        and "…" not in q
    )


def check_quote_integrity(claim: ClaimWork) -> ClaimWork:
    """Keep neutral evidence; keep supports/contradicts only if the quote is acceptable AND found
    verbatim in that URL's text (then `integrity_ok=True`). Failures are discarded and logged."""
    texts = {str(s.document.url): s.document.text for s in claim.sources}
    kept = []
    dropped = 0
    for e in claim.evidence:
        if e.stance == Stance.NEUTRAL:
            kept.append(e)
            continue
        quote = e.quoted_span or ""
        text = texts.get(str(e.url))
        if text is not None and quote_is_acceptable(quote) and contains_verbatim(text, quote):
            kept.append(e.model_copy(update={"integrity_ok": True}))
        else:
            dropped += 1
            log.warning("Discarded evidence: quote not verbatim in source (%s)", e.url)
    updated = claim.model_copy(update={"evidence": tuple(kept)})
    return updated.noted(f"{dropped} quote(s) failed integrity") if dropped else updated