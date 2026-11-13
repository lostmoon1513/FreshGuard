import asyncio
import json

import pytest
from pydantic import SecretStr

from app.engine.providers.errors import (
    LLMOutputError,
    ProviderAuthError,
    ProviderRateLimited,
)
from app.engine.providers.gemini import GeminiProvider
from app.engine.providers.http import RetryPolicy
from app.engine.providers.models import ModelTier
from tests.unit.providers._helpers import FakeHttp, Sleeper, Verdict, gemini_reply, ok, status

KEY = "AIza-test-key"
GOOD = json.dumps({"answer": "yes", "score": 3})


def make(http, **kw):
    return GeminiProvider(KEY, http, sleep=Sleeper(), **kw)


def gen(provider, tier=ModelTier.STANDARD):
    return asyncio.run(
        provider.generate_structured(
            system="Extract.", prompt="Answer text", response_model=Verdict, tier=tier
        )
    )


def test_success_and_request_shape():
    http = FakeHttp(gemini_reply(GOOD))
    assert gen(make(http)) == Verdict(answer="yes", score=3)
    call = http.calls[0]
    assert call["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    )
    assert call["headers"]["x-goog-api-key"] == KEY
    assert KEY not in call["url"]  # never in the URL
    body = call["body"]
    assert body["contents"] == [{"role": "user", "parts": [{"text": "Answer text"}]}]
    assert "responseMimeType" not in body["generationConfig"]  # unverified legacy field
    assert body["generationConfig"]["temperature"] == 0.0
    system_text = body["systemInstruction"]["parts"][0]["text"]
    assert system_text.startswith("Extract.") and '"score"' in system_text


def test_tier_selects_model_and_models_are_configurable():
    http = FakeHttp(gemini_reply(GOOD), gemini_reply(GOOD))
    provider = make(http, models={ModelTier.LIGHT: "my-lite"})
    gen(provider, ModelTier.LIGHT)
    gen(provider, ModelTier.STANDARD)
    assert "/models/my-lite:generateContent" in http.calls[0]["url"]
    assert "/models/gemini-3.8-flash:generateContent" in http.calls[1]["url"]


def test_accepts_secretstr_and_never_reveals_key_in_repr():
    provider = GeminiProvider(SecretStr(KEY), FakeHttp())
    assert KEY not in repr(provider) and KEY not in str(provider)


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_key_is_rejected(bad):
    with pytest.raises(ValueError):
        GeminiProvider(bad, FakeHttp())


def test_fenced_output_is_accepted():
    http = FakeHttp(gemini_reply(f"```json\n{GOOD}\n```"))
    assert gen(make(http)).score == 3


def test_thought_parts_are_ignored():
    reply = ok(
        {
            "candidates": [
                {"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": GOOD}]}}
            ]
        }
    )
    assert gen(make(FakeHttp(reply))).answer == "yes"


@pytest.mark.parametrize(
    "reply",
    [
        ok({}),
        ok({"candidates": []}),
        ok({"promptFeedback": {"blockReason": "SAFETY"}}),
        ok({"candidates": [{"finishReason": "SAFETY"}]}),
        ok({"candidates": [{"content": {"parts": [{"text": "   "}]}}]}),
        gemini_reply("not json at all"),
        gemini_reply('{"answer": "yes"}'),
        ok([1, 2, 3]),
    ],
)
def test_unusable_output_raises_llm_output_error(reply):
    with pytest.raises(LLMOutputError):
        gen(make(FakeHttp(reply)))


def test_block_reason_is_reported():
    with pytest.raises(LLMOutputError, match="SAFETY"):
        gen(make(FakeHttp(ok({"promptFeedback": {"blockReason": "SAFETY"}}))))


def test_http_failures_map_to_provider_errors():
    with pytest.raises(ProviderAuthError):
        gen(make(FakeHttp(status(403))))
    with pytest.raises(ProviderRateLimited):
        gen(make(FakeHttp(status(429, headers={"retry-after": "99"}))))


def test_transient_5xx_is_retried_then_succeeds():
    http = FakeHttp(status(503), gemini_reply(GOOD))
    assert gen(make(http, retry=RetryPolicy(max_attempts=2))).answer == "yes"
    assert len(http.calls) == 2