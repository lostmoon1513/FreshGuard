"""Map any exception raised inside a LangChain model/tool to a `ProviderError`.

LangChain wraps several vendor SDKs, each with its own exception classes. We classify by HTTP
status when the exception carries one, then by class-name hints. The message never contains the
exception text (SDK errors can echo request details), only its class name and status.
"""

from __future__ import annotations

from app.engine.providers.errors import (
    LLMOutputError,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderError,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderUnavailable,
)

_NAME_RULES: tuple[tuple[tuple[str, ...], type[ProviderError]], ...] = (
    (("usagelimit", "quota"), ProviderQuotaExceeded),
    (("ratelimit", "resourceexhausted", "toomanyrequests"), ProviderRateLimited),
    (
        ("authentication", "unauthenticated", "permissiondenied", "invalidapikey", "forbidden",
         "unauthorized"),
        ProviderAuthError,
    ),
    (
        ("timeout", "timedout", "connect", "network", "unavailable", "internalserver"),
        ProviderUnavailable,
    ),
)  # fmt: skip
_OUTPUT_HINTS = ("outputparser", "validationerror", "jsondecode")


def _status_of(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        if obj is None:
            continue
        for attr in ("status_code", "status", "code"):
            value = getattr(obj, attr, None)
            if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
                return value
    return None


def map_exception(provider: str, exc: BaseException) -> ProviderError:
    """Return the `ProviderError` that best describes `exc`. Never includes `str(exc)`."""
    if isinstance(exc, ProviderError):
        return exc
    status = _status_of(exc)
    if status in (401, 403):
        return ProviderAuthError(provider, f"authentication failed (HTTP {status})")
    if status in (432, 433):
        return ProviderQuotaExceeded(provider, f"plan or usage limit exceeded (HTTP {status})")
    if status == 429:
        return ProviderRateLimited(provider, "rate limited (HTTP 429)")
    if status == 408 or (status is not None and 500 <= status < 600):
        return ProviderUnavailable(provider, f"server error or timeout (HTTP {status})")

    names = " ".join(cls.__name__.lower() for cls in type(exc).__mro__)
    status_text = getattr(exc, "status", None)  # e.g. Google: "RESOURCE_EXHAUSTED"
    if isinstance(status_text, str) and len(status_text) < 40:
        names += " " + status_text.lower().replace("_", "")
    if any(hint in names for hint in _OUTPUT_HINTS):
        return LLMOutputError(provider, f"output could not be parsed ({type(exc).__name__})")
    for hints, error_type in _NAME_RULES:
        if any(hint in names for hint in hints):
            return error_type(provider, f"{type(exc).__name__}")
    suffix = f" (HTTP {status})" if status else ""
    return ProviderBadResponse(provider, f"unexpected {type(exc).__name__}{suffix}")