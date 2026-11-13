import asyncio
import json

import pytest

from app.engine.providers.errors import LLMOutputError, ProviderAuthError
from app.engine.providers.groq import GroqProvider
from app.engine.providers.models import ModelTier
from tests.unit.providers._helpers import FakeHttp, Sleeper, Verdict, groq_reply, ok, status

KEY = "gsk-test-key"
GOOD = json.dumps({"answer": "yes", "score": 3})


def make(http, **kw):
    return GroqProvider(KEY, http, sleep=Sleeper(), **kw)


def gen(provider, tier=ModelTier.STANDARD):
    return asyncio.run(
        provider.generate_structured(
            system="Compare.", prompt="Evidence", response_model=Verdict, tier=tier
        )
    )


def test_success_and_request_shape():
    http = FakeHttp(groq_reply(GOOD))
    assert gen(make(http)) == Verdict(answer="yes", score=3)
    call = http.calls[0]
    assert call["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert call["headers"]["authorization"] == f"Bearer {KEY}"
    body = call["body"]
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "JSON" in body["messages"][0]["content"]  # required by Groq JSON mode
    assert body["messages"][1]["content"] == "Evidence"


def test_models_are_configurable_per_tier():
    http = FakeHttp(groq_reply(GOOD), groq_reply(GOOD))
    provider = make(http, models={ModelTier.LIGHT: "small-model"})
    gen(provider, ModelTier.LIGHT)
    gen(provider, ModelTier.STANDARD)
    assert http.calls[0]["body"]["model"] == "small-model"
    assert http.calls[1]["body"]["model"] == "llama-3.3-70b-versatile"


def test_repr_hides_key():
    assert KEY not in repr(make(FakeHttp()))


@pytest.mark.parametrize(
    "reply",
    [
        ok({}),
        ok({"choices": []}),
        ok({"choices": [{"message": {}}]}),
        ok({"choices": [{"message": {"content": None}}]}),
        ok({"choices": [{"message": {"content": "  "}, "finish_reason": "length"}]}),
        groq_reply("nope"),
        groq_reply('{"score": 1}'),
    ],
)
def test_unusable_output_raises(reply):
    with pytest.raises(LLMOutputError):
        gen(make(FakeHttp(reply)))


def test_auth_error_propagates():
    with pytest.raises(ProviderAuthError):
        gen(make(FakeHttp(status(401))))