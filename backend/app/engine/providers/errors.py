"""Provider error hierarchy. Every failure of an LLM or search provider is a `ProviderError`.

Messages never contain API keys: keys travel in headers only and are never put in errors or logs.
"""

from __future__ import annotations


class ProviderError(Exception):
    """Base class. `provider` is the provider name (e.g. "gemini")."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider
        self.message = message


class ProviderUnavailable(ProviderError):
    """Network failure, timeout or HTTP 5xx. Retryable."""


class ProviderRateLimited(ProviderError):
    """HTTP 429. Retryable if the wait is short; `retry_after` is seconds when the API said."""

    def __init__(self, provider: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(provider, message)
        self.retry_after = retry_after


class ProviderQuotaExceeded(ProviderError):
    """Plan or usage limit hit (e.g. Tavily 432/433). Retrying will not help."""


class ProviderAuthError(ProviderError):
    """HTTP 401/403: missing or invalid API key. Retrying will not help."""


class ProviderBadResponse(ProviderError):
    """The provider answered, but the response was rejected or unusable."""


class LLMOutputError(ProviderBadResponse):
    """The LLM's text was not valid JSON, or did not match the requested schema."""


class AllProvidersFailed(ProviderError):
    """Primary and fallback both failed. `errors` holds each underlying error, in order."""

    def __init__(self, provider: str, errors: list[ProviderError]) -> None:
        detail = "; ".join(e.message for e in errors) or "no provider was available"
        super().__init__(provider, f"all providers failed: {detail}")
        self.errors = errors


class FetchError(ProviderError):
    """A web page could not be fetched or read (HTTP error, timeout, wrong type, no text)."""

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__("fetcher", message)
        self.url = url


class UnsafeURLError(FetchError):
    """The URL points somewhere we must never fetch (non-http, private/internal address)."""


class ProviderConfigError(ValueError):
    """Providers cannot be built from the given settings (e.g. fake providers in production)."""