"""FreshGuard Python SDK: a thin client for the FreshGuard stale-answer detection API."""

from freshguard.async_client import AsyncFreshGuard
from freshguard.client import FreshGuard
from freshguard.errors import (
    AuthError,
    ConnectionFailed,
    FreshGuardError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
    VerificationTimeout,
)
from freshguard.models import (
    FRESH,
    LABELS,
    POTENTIALLY_STALE,
    STALE,
    UNVERIFIABLE,
    Claim,
    Evidence,
    Page,
    Verification,
)

__version__ = "0.1.0"

__all__ = [
    "FRESH",
    "LABELS",
    "POTENTIALLY_STALE",
    "STALE",
    "UNVERIFIABLE",
    "AsyncFreshGuard",
    "AuthError",
    "Claim",
    "ConnectionFailed",
    "Evidence",
    "FreshGuard",
    "FreshGuardError",
    "NotFoundError",
    "Page",
    "RateLimitError",
    "ServerError",
    "ValidationError",
    "Verification",
    "VerificationTimeout",
    "__version__",
]