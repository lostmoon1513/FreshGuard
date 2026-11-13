"""Shared helpers for LLM providers: schema-in-prompt and strict JSON parsing/validation."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError

from app.engine.providers.errors import LLMOutputError
from app.engine.providers.models import T

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL | re.IGNORECASE)


def build_system_prompt(system: str, response_model: type[BaseModel]) -> str:
    """Append the JSON contract. We ask for JSON mode AND describe the schema in words, then
    validate with Pydantic ourselves, so behavior does not depend on a vendor's schema dialect."""
    schema = json.dumps(response_model.model_json_schema(), separators=(",", ":"))
    return (
        f"{system.strip()}\n\n"
        "Respond with ONLY one JSON object that conforms to this JSON Schema. "
        "No prose, no markdown fences.\n"
        f"JSON Schema: {schema}"
    )


def parse_model_json(provider: str, text: str, response_model: type[T]) -> T:
    """Parse `text` into `response_model` or raise `LLMOutputError`. Never repairs or guesses."""
    cleaned = text.strip()
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1)
    try:
        data = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise LLMOutputError(provider, "output was not valid JSON") from None
        try:
            data = json.loads(cleaned[start : end + 1])
        except ValueError:
            raise LLMOutputError(provider, "output was not valid JSON") from None
    try:
        return response_model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['type']}"
            for e in exc.errors()[:5]
        )
        raise LLMOutputError(provider, f"output did not match the schema ({problems})") from None
        