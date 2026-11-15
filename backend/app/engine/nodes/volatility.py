"""classify_volatility: how fast can each claim go out of date? LLM proposes, code guards."""

from __future__ import annotations

import re
from datetime import datetime

from app.engine.nodes import prompts
from app.engine.nodes.deps import Deps
from app.engine.nodes.llm_models import VolatilityBatch
from app.engine.nodes.state import ClaimWork
from app.engine.providers.errors import ProviderError
from app.engine.providers.models import ModelTier
from app.schemas.labels import Volatility

_TIME_CUES = re.compile(
    r"\b(current(?:ly)?|latest|newest|now|today|recent(?:ly)?|presently|as of|ceo|president|"
    r"prime minister|chairman|price|costs?|ranked?|record|version|release[sd]?|valuation|"
    r"market cap|population|champion|leads?|headquarter\w*|owns?|owned|reigning|monarch|king|"
    r"queen|chancellor|chair(?:man|woman|person)?|secretary|minister|governor|mayor|director|"
    r"leader|head of|incumbent|winner|holder|most advanced|best)\b",
    re.IGNORECASE,
)
_FAST_CUES = re.compile(
    r"\b(today|this (?:week|month)|right now|latest|price|stock|share price|exchange rate|"
    r"weather|score|live|trending|breaking)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(20\d{2})\b")
MAX_WINDOW_DAYS = 3650


def _recent_year(text: str, now: datetime) -> bool:
    return any(int(y) >= now.year - 1 for y in _YEAR.findall(text))


def guard(
    text: str, proposed: Volatility, window: int | None, now: datetime
) -> tuple[Volatility, int | None]:
    """Deterministic safety net. It can only make a claim MORE time-sensitive, never less:
    static -> slow on time cues or a recent year; slow -> fast on strong fast cues."""
    volatility = proposed
    if volatility == Volatility.STATIC and (_TIME_CUES.search(text) or _recent_year(text, now)):
        volatility = Volatility.SLOW
    if volatility == Volatility.SLOW and _FAST_CUES.search(text):
        volatility = Volatility.FAST
    if volatility == Volatility.STATIC or window is None:
        return volatility, None
    return volatility, min(max(window, 1), MAX_WINDOW_DAYS)


async def classify_volatility(claims: list[ClaimWork], deps: Deps) -> list[ClaimWork]:
    """Missing or failed classification defaults to SLOW (searched), never to STATIC."""
    if not claims:
        return claims
    now = deps.clock()
    proposed: dict[int, tuple[Volatility, int | None]] = {}
    note: str | None = None
    try:
        batch = await deps.llm_call(
            system=prompts.VOLATILITY_SYSTEM,
            prompt=prompts.volatility_prompt([c.text for c in claims], now),
            response_model=VolatilityBatch,
            tier=ModelTier.LIGHT,
        )
        for item in batch.items:
            if 0 <= item.index < len(claims) and item.index not in proposed:
                proposed[item.index] = (item.volatility, item.window_days)
    except ProviderError:
        note = "volatility classifier unavailable; defaulted to slow"
    out: list[ClaimWork] = []
    for i, claim in enumerate(claims):
        vol, window = proposed.get(i, (Volatility.SLOW, None))
        vol, window = guard(claim.text, vol, window, now)
        updated = claim.model_copy(update={"volatility": vol, "window_days": window})
        if i not in proposed:
            updated = updated.noted(note or "no volatility returned; defaulted to slow")
        out.append(updated)
    return out