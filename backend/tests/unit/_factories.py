"""Valid result objects for storage/service/API tests (labels are backed by evidence)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.schemas.claim import ClaimVerdict
from app.schemas.evidence import Evidence
from app.schemas.labels import Label, SourceTier, Stance, VerificationStatus, Volatility
from app.schemas.verification import VerificationResult

T0 = datetime(2026, 11, 13, 3, 0, tzinfo=UTC)


def claim_for(label: Label) -> ClaimVerdict:
    evidence: list[Evidence] = []
    stance = {Label.STALE: Stance.CONTRADICTS, Label.FRESH: Stance.SUPPORTS}.get(label)
    if stance is not None:
        evidence.append(
            Evidence(
                url="https://www.reuters.com/acme",
                tier=SourceTier.TIER_2,
                published_at=T0 - timedelta(days=5),
                fetched_at=T0,
                stance=stance,
                quoted_span="Priya Raman was appointed chief executive of Acme Corp",
                integrity_ok=True,
            )
        )
    return ClaimVerdict(
        text="Jon Lee is the chief executive of Acme Corp",
        volatility=Volatility.SLOW,
        label=label,
        reasoning="test",
        freshness_window_days=365,
        evidence=evidence,
    )


def completed_result(
    rid: str, label: Label, *, created_at: datetime = T0, correction: str | None = None
) -> VerificationResult:
    return VerificationResult(
        id=rid,
        status=VerificationStatus.COMPLETED,
        label=label,
        confidence=0.0 if label == Label.UNVERIFIABLE else 0.6,
        claims=[claim_for(label)],
        suggested_correction=correction if label == Label.STALE else None,
        created_at=created_at,
        finished_at=created_at + timedelta(seconds=5),
    )