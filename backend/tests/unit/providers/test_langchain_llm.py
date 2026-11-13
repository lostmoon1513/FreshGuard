import asyncio
import json
from types import SimpleNamespace

import pytest

from app.engine.providers import FallbackLLM
from app.engine.providers.errors import (
    AllProvidersFailed,
    LLMOutputError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.engine.providers.langchain_llm import LangChainLLM, message_text
from app.engine.providers.models import ModelTier
from tests.unit.providers._helpers import Verdict

GOOD = json.dumps({"answer": "yes", "score": 3})


class FakeChatModel:
    """Stands in for a LangChain chat model: only `ainvoke(messages)` is needed."""

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.reply)


def make(std=None, lite=None, name="gemini"):
    std = std or FakeChatModel(GOOD)
    return LangChainLLM(name, {ModelTier.STANDARD: std, ModelTier.LIGHT: lite or std})


def gen(llm, tier=ModelTier.STANDARD):
    return asyncio.run(
        llm.generate_structured(
            system="Extract.", prompt="Answer text", response_model=Verdict, tier=tier
        )
    )


def test_success_and_message_shape():
    model = FakeChatModel(GOOD)
    assert gen(make(model)) == Verdict(answer="yes", score=3)
    (role_sys, sys_text), (role_user, user_text) = model.calls[0]
    assert (role_sys, role_user) == ("system", "human")
    assert sys_text.startswith("Extract.") and '"score"' in sys_text  # schema is in the prompt
    assert user_text == "Answer text"


def test_tier_selects_the_model():
    std, lite = FakeChatModel(GOOD), FakeChatModel(GOOD)
    llm = make(std, lite)
    gen(llm, ModelTier.LIGHT)
    assert (len(std.calls), len(lite.calls)) == (0, 1)
    gen(llm, ModelTier.STANDARD)
    assert (len(std.calls), len(lite.calls)) == (1, 1)


def test_every_tier_needs_a_model():
    with pytest.raises(ValueError, match="every tier"):
        LangChainLLM("x", {ModelTier.STANDARD: FakeChatModel(GOOD)})


def test_fenced_output_and_block_list_content():
    assert gen(make(FakeChatModel(f"```json\n{GOOD}\n```"))).score == 3
    blocks = [
        {"type": "thinking", "thinking": "hmm"},
        {"type": "text", "text": GOOD[:10]},
        GOOD[10:],
    ]
    assert gen(make(FakeChatModel(blocks))) == Verdict(answer="yes", score=3)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("abc", "abc"),
        (["a", {"type": "text", "text": "b"}, {"type": "thinking", "text": "no"}, 5], "ab"),
        ([{"text": "untyped blocks count as text"}], "untyped blocks count as text"),
        (None, ""),
        (123, ""),
    ],
)
def test_message_text(content, expected):
    assert message_text(content) == expected


@pytest.mark.parametrize("reply", ["", "   ", None, []])
def test_empty_output_is_an_error(reply):
    with pytest.raises(LLMOutputError, match="empty"):
        gen(make(FakeChatModel(reply)))


@pytest.mark.parametrize("reply", ["not json", '{"answer": "yes"}', '{"answer": 1, "score": "x"}'])
def test_invalid_output_is_rejected_never_repaired(reply):
    with pytest.raises(LLMOutputError):
        gen(make(FakeChatModel(reply)))


def test_exceptions_are_mapped_and_the_original_text_is_not_leaked():
    class RateLimitError(Exception):
        status_code = 429

    llm = make(FakeChatModel(error=RateLimitError("key=AIza-secret exhausted")))
    with pytest.raises(ProviderRateLimited) as info:
        gen(llm)
    assert "AIza" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_cancellation_is_not_swallowed():
    llm = make(FakeChatModel(error=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        gen(llm)


def test_works_inside_the_fallback_chain():
    class ConnectError(Exception):
        pass

    primary = make(FakeChatModel(error=ConnectError("down")), name="gemini")
    backup = make(FakeChatModel(GOOD), name="groq")
    chain = FallbackLLM(primary, backup)
    assert asyncio.run(
        chain.generate_structured(system="s", prompt="p", response_model=Verdict)
    ) == Verdict(answer="yes", score=3)

    both_down = FallbackLLM(
        make(FakeChatModel(error=ConnectError("a")), name="gemini"),
        make(FakeChatModel(error=ConnectError("b")), name="groq"),
    )
    with pytest.raises(AllProvidersFailed) as info:
        asyncio.run(both_down.generate_structured(system="s", prompt="p", response_model=Verdict))
    assert all(isinstance(e, ProviderUnavailable) for e in info.value.errors)


def test_repr_has_no_secrets():
    assert repr(make()) == "LangChainLLM(name='gemini')"