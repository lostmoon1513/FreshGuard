"""Result objects. Plain frozen dataclasses built from the API's JSON (no extra dependencies)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

FRESH = "fresh"
STALE = "stale"
POTENTIALLY_STALE = "potentially_stale"
UNVERIFIABLE = "unverifiable"
LABELS = (FRESH, STALE, POTENTIALLY_STALE, UNVERIFIABLE)
DONE_STATUSES = ("completed", "failed")


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True)
class Evidence:
    url: str
    tier: int
    stance: str  # "supports" | "contradicts" | "neutral"
    quoted_span: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    integrity_ok: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Evidence:
        return cls(
            url=str(data.get("url", "")),
            tier=int(data.get("tier", 3)),
            stance=str(data.get("stance", "neutral")),
            quoted_span=data.get("quoted_span"),
            published_at=_dt(data.get("published_at")),
            fetched_at=_dt(data.get("fetched_at")),
            integrity_ok=data.get("integrity_ok"),
        )


@dataclass(frozen=True)
class Claim:
    text: str
    label: str
    volatility: str = "slow"
    reasoning: str = ""
    freshness_window_days: int | None = None
    evidence: tuple[Evidence, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Claim:
        return cls(
            text=str(data.get("text", "")),
            label=str(data.get("label", UNVERIFIABLE)),
            volatility=str(data.get("volatility", "slow")),
            reasoning=str(data.get("reasoning", "")),
            freshness_window_days=data.get("freshness_window_days"),
            evidence=tuple(Evidence.from_dict(e) for e in data.get("evidence") or ()),
        )


@dataclass(frozen=True)
class Verification:
    id: str
    status: str  # "pending" | "running" | "completed" | "failed"
    label: str | None = None
    confidence: float | None = None
    suggested_correction: str | None = None
    error: str | None = None
    claims: tuple[Claim, ...] = ()
    created_at: datetime | None = None
    finished_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Verification:
        return cls(
            id=str(data["id"]),
            status=str(data.get("status", "pending")),
            label=data.get("label"),
            confidence=data.get("confidence"),
            suggested_correction=data.get("suggested_correction"),
            error=data.get("error"),
            claims=tuple(Claim.from_dict(c) for c in data.get("claims") or ()),
            created_at=_dt(data.get("created_at")),
            finished_at=_dt(data.get("finished_at")),
            metadata=dict(data.get("metadata") or {}),
        )

    @property
    def is_done(self) -> bool:
        """True once the job has finished, successfully or not."""
        return self.status in DONE_STATUSES

    @property
    def is_stale(self) -> bool:
        return self.label == STALE

    @property
    def should_warn(self) -> bool:
        """Show the user a warning: the answer is stale or possibly out of date."""
        return self.label in (STALE, POTENTIALLY_STALE)


@dataclass(frozen=True)
class Page:
    items: tuple[Verification, ...]
    next_before: str | None = None