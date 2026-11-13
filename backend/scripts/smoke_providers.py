"""Live smoke test of the real providers. Makes a few tiny real API calls (uses a little quota).

Run from the backend/ folder (venv active, keys in .env):

    python scripts/smoke_providers.py

What it checks:
  1. the libraries are installed (LangGraph, LangChain integrations, httpx) and their versions;
  2. for BOTH backends ("rest" = plain HTTP, "langchain" = LangChain integrations) and for every
     provider that has a key: one structured LLM call or one search;
  3. the real fallback chain + cache that the engine will use (your PROVIDER_BACKEND setting).

Compare the two backends' search lines: `date=` shows whether publish dates survive. It prints
only OK/FAIL and short, key-free details. Exit code 0 = everything configured works.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.engine.providers import build_llm, build_search
from app.engine.providers import langchain_backend as lc
from app.engine.providers.errors import ProviderError
from app.engine.providers.gemini import GeminiProvider
from app.engine.providers.groq import GroqProvider
from app.engine.providers.http import HttpClient
from app.engine.providers.langchain_llm import LangChainLLM
from app.engine.providers.langchain_search import LangChainSerperSearch, LangChainTavilySearch
from app.engine.providers.models import ModelTier
from app.engine.providers.serper import SerperSearch
from app.engine.providers.tavily import TavilySearch

QUERY = "latest stable Python release"
PACKAGES = (
    "langgraph",
    "langchain-core",
    "langchain-google-genai",
    "langchain-groq",
    "langchain-tavily",
    "langchain-community",
    "httpx",
    "pydantic",
)


class Fact(BaseModel):
    subject: str
    value: str


Check = Callable[[], Awaitable[str]]


def _has(secret: Any) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


async def _libraries_check() -> str:
    found, missing = [], []
    for name in PACKAGES:
        try:
            found.append(f"{name}=={version(name)}")
        except PackageNotFoundError:
            missing.append(name)
    if missing:
        raise ProviderError("libraries", "not installed: " + ", ".join(missing))
    from langgraph.graph import StateGraph  # noqa: F401  (import check only)

    return ", ".join(found)


async def _llm_check(llm: Any, tier: ModelTier = ModelTier.STANDARD) -> str:
    fact = await llm.generate_structured(
        system="Extract the subject and the value from the statement.",
        prompt="The speed of light in vacuum is 299792458 metres per second.",
        response_model=Fact,
        tier=tier,
    )
    return f"got subject={fact.subject!r}"


async def _search_check(search: Any) -> str:
    hits = await search.search(QUERY, max_results=3)
    if not hits:
        raise ProviderError(getattr(search, "name", "search"), "returned no results")
    parts = [
        f"{h.url.host} content={'yes' if h.content else 'snippet-only'} "
        f"date={h.published_at.date() if h.published_at else None}"
        for h in hits
    ]
    return f"{len(hits)} hit(s): " + "; ".join(parts)


def _rest_checks(settings: Settings, http: HttpClient) -> list[tuple[str, Check]]:
    checks: list[tuple[str, Check]] = []
    if _has(settings.gemini_api_key):
        models = {
            ModelTier.STANDARD: settings.gemini_model_standard,
            ModelTier.LIGHT: settings.gemini_model_light,
        }
        gem = GeminiProvider(settings.gemini_api_key, http, models=models)  # type: ignore[arg-type]
        checks.append((f"[rest] gemini {models[ModelTier.STANDARD]}", lambda: _llm_check(gem)))
        checks.append(
            (f"[rest] gemini {models[ModelTier.LIGHT]}", lambda: _llm_check(gem, ModelTier.LIGHT))
        )
    if _has(settings.groq_api_key):
        groq = GroqProvider(
            settings.groq_api_key,  # type: ignore[arg-type]
            http,
            models={
                ModelTier.STANDARD: settings.groq_model_standard,
                ModelTier.LIGHT: settings.groq_model_light,
            },
        )
        checks.append((f"[rest] groq {settings.groq_model_standard}", lambda: _llm_check(groq)))
    if _has(settings.tavily_api_key):
        tav = TavilySearch(settings.tavily_api_key, http)  # type: ignore[arg-type]
        checks.append(("[rest] tavily search", lambda: _search_check(tav)))
    if _has(settings.serper_api_key):
        ser = SerperSearch(settings.serper_api_key, http)  # type: ignore[arg-type]
        checks.append(("[rest] serper search", lambda: _search_check(ser)))
    return checks


def _langchain_checks(settings: Settings) -> list[tuple[str, Check]]:
    checks: list[tuple[str, Check]] = []

    def llm(name: str) -> LangChainLLM:
        return LangChainLLM(name, {t: lc.make_chat_model(settings, name, t) for t in ModelTier})

    if _has(settings.gemini_api_key):
        checks.append(("[langchain] gemini", lambda: _llm_check(llm("gemini"))))
        checks.append(
            ("[langchain] gemini light", lambda: _llm_check(llm("gemini"), ModelTier.LIGHT))
        )
    if _has(settings.groq_api_key):
        checks.append(("[langchain] groq", lambda: _llm_check(llm("groq"))))
    if _has(settings.tavily_api_key):
        tavily = LangChainTavilySearch(lc.make_search_tool(settings, "tavily"))
        checks.append(("[langchain] tavily search", lambda: _search_check(tavily)))
    if _has(settings.serper_api_key):
        serper = LangChainSerperSearch(lc.make_search_tool(settings, "serper"))
        checks.append(("[langchain] serper search", lambda: _search_check(serper)))
    return checks


def build_checks(settings: Settings, http: HttpClient) -> list[tuple[str, Check]]:
    checks: list[tuple[str, Check]] = [("libraries", _libraries_check)]
    checks += _rest_checks(settings, http)
    checks += _langchain_checks(settings)
    # The real path the engine will use: fallback chain + cache, for the configured backend.
    chain_llm = build_llm(settings, http=http)
    chain_search = build_search(settings, http=http)
    label = f"[engine, backend={settings.provider_backend}]"
    checks.append((f"{label} LLM chain {chain_llm.name}", lambda: _llm_check(chain_llm)))
    checks.append(
        (f"{label} search chain {chain_search.name}", lambda: _search_check(chain_search))
    )
    return checks


async def run_checks(settings: Settings, http: HttpClient) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    try:
        checks = build_checks(settings, http)
    except ImportError as exc:  # a LangChain package is missing: report it, don't crash
        return [("setup", False, str(exc))]
    for name, check in checks:
        try:
            results.append((name, True, await check()))
        except ProviderError as exc:  # messages never contain keys
            results.append((name, False, f"{type(exc).__name__}: {exc.message}"))
        except Exception as exc:  # noqa: BLE001 - a smoke test must report, not crash
            results.append((name, False, type(exc).__name__))
    return results


async def main() -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        print("Settings are invalid (check your .env):")
        for err in exc.errors():
            print(f"  - {'.'.join(str(p) for p in err['loc']) or 'settings'}: {err['msg']}")
        return 1

    from app.engine.providers.httpx_client import HttpxClient  # needs httpx installed

    http = HttpxClient()
    try:
        results = await run_checks(settings, http)
    finally:
        await http.aclose()

    for name, ok, detail in results:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))