"""The ONLY module that imports LangChain integration packages. Builds real LangChain objects.

Imports are lazy so the rest of the engine (and the whole test suite) runs without them.
Verified against the docs: `ChatGoogleGenerativeAI(model=..., api_key=...)`; the LangChain Tavily
tool reads `TAVILY_API_KEY` from the environment; `GoogleSerperAPIWrapper` reads `SERPER_API_KEY`.
Not verifiable offline, so confirm with `scripts/smoke_providers.py`: the `ChatGroq` `api_key`
argument and `GoogleSerperAPIWrapper(serper_api_key=...)`.
"""

from __future__ import annotations

import os
from typing import Any

from app.engine.providers.models import ModelTier
from app.engine.providers.secrets import secret_value

# Search tools are built once with the largest result count; adapters slice to the request.
TOOL_MAX_RESULTS = 20


def _need(module: str, package: str) -> None:
    try:
        __import__(module)
    except ImportError as exc:
        raise ImportError(
            f"The LangChain backend needs '{package}'. Run: pip install -e \".[dev]\"  "
            "(or set PROVIDER_BACKEND=rest to use the plain REST providers)."
        ) from exc


def make_chat_model(settings: Any, provider: str, tier: ModelTier) -> Any:
    """A LangChain chat model for `provider` ('gemini' | 'groq') and `tier`."""
    retries = max(0, int(settings.provider_max_attempts) - 1)
    timeout = float(settings.llm_timeout_seconds)
    if provider == "gemini":
        _need("langchain_google_genai", "langchain-google-genai")
        from langchain_google_genai import ChatGoogleGenerativeAI

        model = (
            settings.gemini_model_light
            if tier == ModelTier.LIGHT
            else settings.gemini_model_standard
        )
        # Temperature is left at the library default: Google advises against lowering it
        # for Gemini 3+ models.
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=secret_value(settings.gemini_api_key),
            timeout=timeout,
            max_retries=retries,
        )
    if provider == "groq":
        _need("langchain_groq", "langchain-groq")
        from langchain_groq import ChatGroq

        model = (
            settings.groq_model_light if tier == ModelTier.LIGHT else settings.groq_model_standard
        )
        return ChatGroq(
            model=model,
            api_key=secret_value(settings.groq_api_key),
            temperature=0,
            timeout=timeout,
            max_retries=retries,
        )
    raise ValueError(f"Unknown LLM provider: {provider}")


def make_search_tool(settings: Any, provider: str) -> Any:
    """A LangChain Tavily tool or Serper wrapper, depending on `provider`."""
    if provider == "tavily":
        _need("langchain_tavily", "langchain-tavily")
        from langchain_tavily import TavilySearch

        # The documented way to give the tool its key is the environment variable.
        os.environ.setdefault("TAVILY_API_KEY", secret_value(settings.tavily_api_key))
        return TavilySearch(max_results=TOOL_MAX_RESULTS, topic="general", include_raw_content=True)
    if provider == "serper":
        _need("langchain_community", "langchain-community")
        from langchain_community.utilities import GoogleSerperAPIWrapper

        return GoogleSerperAPIWrapper(
            serper_api_key=secret_value(settings.serper_api_key), k=TOOL_MAX_RESULTS
        )
    raise ValueError(f"Unknown search provider: {provider}")