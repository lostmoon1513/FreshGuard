import pytest

from app.engine.providers.errors import (
    LLMOutputError,
    ProviderAuthError,
    ProviderBadResponse,
    ProviderQuotaExceeded,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.engine.providers.langchain_errors import map_exception

SECRET_TEXT = "request failed for key=AIza-super-secret"


def err(name, message=SECRET_TEXT, **attrs):
    """Build an exception whose CLASS NAME is `name` (like a vendor SDK's)."""
    exc = type(name, (Exception,), {})(message)
    for key, value in attrs.items():
        setattr(exc, key, value)
    return exc


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimited),
        (432, ProviderQuotaExceeded),
        (433, ProviderQuotaExceeded),
        (408, ProviderUnavailable),
        (500, ProviderUnavailable),
        (503, ProviderUnavailable),
        (400, ProviderBadResponse),
        (404, ProviderBadResponse),
    ],
)
@pytest.mark.parametrize("attr", ["status_code", "code"])
def test_http_status_on_the_exception(attr, status, expected):
    assert isinstance(map_exception("p", err("SomeApiError", **{attr: status})), expected)


def test_http_status_on_exception_response():
    response = type("R", (), {"status_code": 429})()
    assert isinstance(map_exception("p", err("Boom", response=response)), ProviderRateLimited)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("RateLimitError", ProviderRateLimited),
        ("ResourceExhausted", ProviderRateLimited),
        ("UsageLimitExceededError", ProviderQuotaExceeded),
        ("AuthenticationError", ProviderAuthError),
        ("PermissionDenied", ProviderAuthError),
        ("InvalidAPIKeyError", ProviderAuthError),
        ("ForbiddenError", ProviderAuthError),
        ("APITimeoutError", ProviderUnavailable),
        ("ConnectError", ProviderUnavailable),
        ("ServiceUnavailable", ProviderUnavailable),
        ("OutputParserException", LLMOutputError),
        ("ValidationError", LLMOutputError),
        ("JSONDecodeError", LLMOutputError),
        ("SomethingElseEntirely", ProviderBadResponse),
    ],
)
def test_class_name_hints(name, expected):
    assert isinstance(map_exception("p", err(name)), expected)


def test_google_style_status_text():
    exc = err("ClientError", status="RESOURCE_EXHAUSTED")
    assert isinstance(map_exception("p", exc), ProviderRateLimited)


def test_subclass_names_are_found_through_the_mro():
    base = type("RateLimitError", (Exception,), {})
    child = type("MyCustomError", (base,), {})
    assert isinstance(map_exception("p", child("x")), ProviderRateLimited)


def test_status_beats_name():
    assert isinstance(map_exception("p", err("RateLimitError", status_code=401)), ProviderAuthError)


def test_existing_provider_errors_pass_through_unchanged():
    original = ProviderAuthError("x", "already mapped")
    assert map_exception("p", original) is original


@pytest.mark.parametrize(
    "exc",
    [err("RateLimitError"), err("Weird"), err("X", status_code=500), err("OutputParserException")],
)
def test_messages_never_contain_the_exception_text(exc):
    mapped = map_exception("gemini", exc)
    assert "AIza" not in str(mapped) and "secret" not in str(mapped).lower()
    assert mapped.provider == "gemini"


def test_bool_and_out_of_range_codes_are_ignored():
    assert isinstance(map_exception("p", err("Weird", code=True)), ProviderBadResponse)
    assert isinstance(map_exception("p", err("Weird", code=99999)), ProviderBadResponse)