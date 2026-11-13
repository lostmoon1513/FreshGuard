"""LLMProvider backed by LangChain chat models (ChatGoogleGenerativeAI, ChatGroq, ...).

Duck-typed on purpose: a "chat model" is anything with `async ainvoke(messages)` returning an
object with `.content`. That is the one LangChain call we rely on, so these adapters can be
tested here without LangChain installed, and real models are built only in `langchain_backend.py`.

We keep our own contract on top of LangChain: the JSON schema goes in the prompt, the reply is
validated strictly by Pydantic (`LLMOutputError` on failure, never repaired), and every failure
is mapped to a `ProviderError` so `FallbackLLM` works unchanged. Retries/timeouts are handled by
the LangChain model itself (`max_retries`, `timeout`), so we do not retry here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from app.engine.providers.errors import LLMOutputError
from app.engine.providers.langchain_errors import map_exception
from app.engine.providers.llm_common import build_system_prompt, parse_model_json
from app.engine.providers.models import ModelTier, T

log = logging.getLogger(__name__)


def message_text(content: Any) -> str:
    """Text of an AIMessage `.content`: a str, or a list of blocks (thinking blocks are skipped)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif (
                isinstance(block, dict)
                and block.get("type", "text") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
        return "".join(parts)
    return ""


class LangChainLLM:
    def __init__(self, name: str, models: Mapping[ModelTier, Any]) -> None:
        missing = [tier for tier in ModelTier if tier not in models]
        if missing:
            raise ValueError(f"A chat model is required for every tier; missing: {missing}")
        self.name = name
        self._models = dict(models)

    def __repr__(self) -> str:
        return f"LangChainLLM(name={self.name!r})"

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tier: ModelTier = ModelTier.STANDARD,
    ) -> T:
        messages = [("system", build_system_prompt(system, response_model)), ("human", prompt)]
        try:
            reply = await self._models[tier].ainvoke(messages)
        except Exception as exc:  # noqa: BLE001 - SDK exception types are unknowable; mapped below
            error = map_exception(self.name, exc)
            log.warning(
                "langchain llm call failed",
                extra={"provider": self.name, "error": type(error).__name__},
            )
            raise error from None
        text = message_text(getattr(reply, "content", reply))
        if not text.strip():
            raise LLMOutputError(self.name, "empty output")
        return parse_model_json(self.name, text, response_model)