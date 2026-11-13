"""assemble_result: claim verdicts -> the final VerificationResult (or a FAILED one)."""

from __future__ import annotations

from datetime import datetime

from app.engine.nodes.state import ClaimWork, needs_search
from app.engine.rules.scoring import aggregate_answer
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationResult


def fail_result(
    result_id: str, error: str, created_at: datetime, finished_at: datetime
) -> VerificationResult:
    return VerificationResult(
        id=result_id,
        status=VerificationStatus.FAILED,
        error=error,
        created_at=created_at,
        finished_at=finished_at,
    )


def assemble_result(
    result_id: str, claims: list[ClaimWork], created_at: datetime, finished_at: datetime
) -> VerificationResult:
    """No claims -> UNVERIFIABLE. If every searchable claim hit a provider outage and none found
    anything, the run FAILED (we could not check) rather than reporting 'unverifiable'."""
    searchable = [c for c in claims if needs_search(c)]
    if searchable and all(c.provider_failed and not c.evidence for c in searchable):
        return fail_result(
            result_id, "Search or model providers were unavailable.", created_at, finished_at
        )
    verdicts = [c.verdict for c in claims if c.verdict is not None]
    label, confidence = aggregate_answer(
        (v.label, c.decision.confidence)
        for c, v in ((c, c.verdict) for c in claims if c.verdict and c.decision)
    )
    correction = None
    if label == Label.STALE:
        parts = [
            c.correction
            for c in claims
            if c.correction and c.verdict and c.verdict.label == Label.STALE
        ]
        correction = " ".join(parts) or None
    return VerificationResult(
        id=result_id,
        status=VerificationStatus.COMPLETED,
        label=label,
        confidence=confidence,
        claims=verdicts,
        suggested_correction=correction,
        created_at=created_at,
        finished_at=finished_at,
    )