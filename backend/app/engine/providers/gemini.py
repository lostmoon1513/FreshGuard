"""Gemini LLM provider (REST generateContent). Free-tier friendly: Flash / Flash-Lite.

We do not use Gemini's server-side JSON mode: its field names changed in the current docs and
could not be verified. The schema is described in the prompt and the reply is validated by
Pydantic, which works the same on every provider.

Auth is the `x-goog-api-key` header, so the key never appears in a URL or a log line.
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

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODELS = {ModelTier.STANDARD: "gemini-3.8-flash", ModelTier.LIGHT: "gemini-3.5-flash-lite"}


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: SecretStr | str,
        client: HttpClient,
        *,
        models: dict[ModelTier, str] | None = None,
        retry: RetryPolicy = DEFAULT_RETRY,
        timeout: float = 30.0,
        max_output_tokens: int = 4096,
        base_url: str = DEFAULT_BASE_URL,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._key = secret_value(api_key)
        self._client = client
        self._models = {**DEFAULT_MODELS, **(models or {})}
        self._retry = retry
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep

    def __repr__(self) -> str:  # never show the key
        return f"GeminiProvider(models={self._models!r})"

    async def generate_structured(
        self,
        *,
        system: str,
        prompt: str,
        response_model: type[T],
        tier: ModelTier = ModelTier.STANDARD,
    ) -> T:
        model = self._models[tier]
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": build_system_prompt(system, response_model)}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": self._max_output_tokens,
            },
        }
        data = await post_json_with_retry(
            self._client,
            provider=self.name,
            url=f"{self._base_url}/models/{model}:generateContent",
            headers={"x-goog-api-key": self._key, "content-type": "application/json"},
            body=body,
            timeout=self._timeout,
            retry=self._retry,
            sleep=self._sleep,
        )
        return parse_model_json(self.name, self._extract_text(data), response_model)

    def _extract_text(self, data: Any) -> str:
        candidates = data.get("candidates") if isinstance(data, dict) else None
        if not candidates or not isinstance(candidates[0], dict):
            block = (
                (data.get("promptFeedback") or {}).get("blockReason")
                if isinstance(data, dict)
                else None
            )
            raise LLMOutputError(self.name, f"no candidates returned (blockReason={block})")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(
            p["text"]
            for p in parts
            if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")
        )
        if not text.strip():
            raise LLMOutputError(
                self.name, f"empty output (finishReason={candidate.get('finishReason')})"
            )
        return text