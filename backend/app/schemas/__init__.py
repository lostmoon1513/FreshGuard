"""Shared Pydantic types: the single source of truth for data shapes.

Used by the engine, the API and the database layer. Imports nothing from them.
"""

from app.schemas.claim import Claim, ClaimVerdict
from app.schemas.evidence import Document, Evidence
from app.schemas.labels import (
    Label,
    SourceTier,
    Stance,
    VerificationStatus,
    Volatility,
    worst_label,
)
from app.schemas.verification import VerificationRequest, VerificationResult

__all__ = [
    "Claim",
    "ClaimVerdict",
    "Document",
    "Evidence",
    "Label",
    "SourceTier",
    "Stance",
    "VerificationRequest",
    "VerificationResult",
    "VerificationStatus",
    "Volatility",
    "worst_label",
]
