"""Exceptions. Everything the SDK raises is a `FreshGuardError`."""

from __future__ import annotations


class FreshGuardError(Exception):
    """Base class. `status` is the HTTP status if there was one; `code` is the API error code."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.request_id = request_id


class AuthError(FreshGuardError):
    """401: missing or wrong API key."""


class NotFoundError(FreshGuardError):
    """404: unknown verification id."""


class ValidationError(FreshGuardError):
    """422 (or a bad argument caught before sending)."""


class RateLimitError(FreshGuardError):
    """429: too many requests. `retry_after` is the number of seconds to wait, if known."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(FreshGuardError):
    """5xx, or a response that is not valid FreshGuard JSON."""


class ConnectionFailed(FreshGuardError):
    """The server could not be reached (network error or timeout)."""


class VerificationTimeout(FreshGuardError):
    """We stopped waiting. The job keeps running on the server: call `get` or `wait` again."""

    def __init__(self, verification_id: str, waited: float) -> None:
        super().__init__(
            f"Verification {verification_id} not finished after {waited:g}s; it is still running."
        )
        self.verification_id = verification_id
        self.waited = waited