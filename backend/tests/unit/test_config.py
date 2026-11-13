import pytest
from pydantic import ValidationError

from app.config import Settings


def make(**kwargs):
    """Build Settings ignoring any real .env file."""
    return Settings(_env_file=None, **kwargs)


def test_default_providers_are_real_so_missing_keys_fail_loudly():
    with pytest.raises(ValidationError) as exc:
        make()
    message = str(exc.value)
    assert "GEMINI_API_KEY" in message
    assert "TAVILY_API_KEY" in message


def test_fake_providers_need_no_keys_in_test_environment():
    settings = make(environment="test", llm_provider="fake", search_provider="fake")
    assert settings.llm_provider == "fake"


def test_fake_providers_are_rejected_in_production():
    with pytest.raises(ValidationError, match="not allowed in production"):
        make(environment="production", llm_provider="fake", search_provider="fake")
    with pytest.raises(ValidationError, match="not allowed in production"):
        make(
            environment="production",
            llm_provider="gemini",
            gemini_api_key="k",
            search_provider="fake",
        )


def test_real_providers_with_keys_are_accepted_in_production():
    settings = make(
        environment="production",
        gemini_api_key="g-key",
        tavily_api_key="t-key",
        freshguard_api_key="api-key",
    )
    assert settings.llm_provider == "gemini"


def test_production_requires_an_api_key():
    with pytest.raises(ValidationError, match="FRESHGUARD_API_KEY"):
        make(environment="production", gemini_api_key="g-key", tavily_api_key="t-key")
    with pytest.raises(ValidationError, match="FRESHGUARD_API_KEY"):
        make(
            environment="production",
            gemini_api_key="g-key",
            tavily_api_key="t-key",
            freshguard_api_key="  ",
        )


def test_api_defaults_are_sane():
    settings = make(environment="test", llm_provider="fake", search_provider="fake")
    assert settings.freshguard_api_key is None
    assert settings.max_concurrent_verifications == 2
    assert settings.rate_limit_per_minute == 30 and settings.cors_origins == ""


def test_blank_key_counts_as_missing():
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        make(gemini_api_key="   ", tavily_api_key="t-key")


def test_alternate_providers_require_their_own_keys():
    with pytest.raises(ValidationError, match="GROQ_API_KEY"):
        make(llm_provider="groq", search_provider="fake", environment="test")
    ok = make(llm_provider="groq", groq_api_key="x", search_provider="fake", environment="test")
    assert ok.llm_provider == "groq"


def test_secrets_are_not_leaked_in_repr():
    settings = make(gemini_api_key="super-secret-value", tavily_api_key="another-secret")
    assert "super-secret-value" not in repr(settings)
    assert "another-secret" not in str(settings)


def test_values_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("SEARCH_PROVIDER", "fake")
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("MAX_CLAIMS_PER_ANSWER", "7")
    settings = make()
    assert settings.max_claims_per_answer == 7


def test_limits_are_range_checked():
    with pytest.raises(ValidationError):
        make(
            environment="test",
            llm_provider="fake",
            search_provider="fake",
            max_claims_per_answer=0,
        )


def test_provider_tuning_defaults():
    s = make(environment="test", llm_provider="fake", search_provider="fake")
    assert s.gemini_model_standard == "gemini-3.8-flash"
    assert s.gemini_model_light == "gemini-3.5-flash-lite"
    assert s.provider_max_attempts == 3
    assert s.search_cache_ttl_seconds == 6 * 3600


def test_provider_tuning_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("SEARCH_PROVIDER", "fake")
    monkeypatch.setenv("GEMINI_MODEL_STANDARD", "my-model")
    monkeypatch.setenv("SEARCH_CACHE_TTL_SECONDS", "0")
    s = make()
    assert s.gemini_model_standard == "my-model"
    assert s.search_cache_ttl_seconds == 0  # 0 disables the cache


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("llm_timeout_seconds", 0),
        ("llm_timeout_seconds", 500),
        ("search_timeout_seconds", -1),
        ("provider_max_attempts", 0),
        ("provider_max_attempts", 9),
        ("search_cache_ttl_seconds", -1),
    ],
)
def test_provider_tuning_is_range_checked(field, value):
    with pytest.raises(ValidationError):
        make(environment="test", llm_provider="fake", search_provider="fake", **{field: value})


def test_provider_backend_defaults_to_langchain_and_rejects_unknown_values():
    s = make(environment="test", llm_provider="fake", search_provider="fake")
    assert s.provider_backend == "langchain"
    assert (
        make(
            environment="test", llm_provider="fake", search_provider="fake", provider_backend="rest"
        ).provider_backend
        == "rest"
    )
    with pytest.raises(ValidationError):
        make(
            environment="test",
            llm_provider="fake",
            search_provider="fake",
            provider_backend="magic",
        )