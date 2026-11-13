"""Groq LLM provider (OpenAI-compatible chat completions, JSON mode). Used as the fallback LLM.

`response_format: json_object` works on every Groq model; the schema is described in the prompt
and validated by Pydantic afterwards.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import SecretStr

from app.engine.providers.errors import LLMOutputError
from app.engine.providers.http import (
    DEFAULT_RETRY,
    HttpClient,
    RetryPolicy,
    Sleep,
    post_json_with_retry,
)
from app.engine.providers.llm_common import build_system_prompt, parse_model_json
from app.engine.providers.models import ModelTier, T
from app.engine.providers.secrets import secret_value

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODELS = {
    ModelTier.STANDARD: "llama-3.3-70b-versatile",
    ModelTier.LIGHT: "llama-3.3-70b-versatile",
}


class GroqProvider:
    name = "groq"

    def __init__(
        self,
        api_key: SecretStr | str,
        client: HttpClient,
        *,
        models: dict[ModelTier, str] | None = None,
        retry: RetryPolicy = DEFAULT_RETRY,
        timeout: float = 30.0,
        base_url: str = DEFAULT_BASE_URL,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._key = secret_value(api_key)
        self._client = client
        self._models = {**DEFAULT_MODELS, **(models or {})}
        self._retry = retry
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"GroqProvider(models={self._models!r})"

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tier: ModelTier = ModelTier.STANDARD,
    ) -> T:
        body: dict[str, Any] = {
            "model": self._models[tier],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": build_system_prompt(system, response_model)},
                {"role": "user", "content": prompt},
            ],
        }
        data = await post_json_with_retry(
            self._client,
            provider=self.name,
            url=f"{self._base_url}/chat/completions",
            headers={"authorization": f"Bearer {self._key}", "content-type": "application/json"},
            body=body,
            timeout=self._timeout,
            retry=self._retry,
            sleep=self._sleep,
        )
        return parse_model_json(self.name, self._extract_text(data), response_model)

    def _extract_text(self, data: Any) -> str:
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMOutputError(self.name, "response had no choices[0].message.content") from None
        if not isinstance(text, str) or not text.strip():
            raise LLMOutputError(
                self.name, f"empty output (finish_reason={choice.get('finish_reason')})"
            )
        return text