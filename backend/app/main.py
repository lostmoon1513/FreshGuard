"""Process entry point.  Run:  uvicorn app.main:app --port 8000

`app` is built lazily on first access, so importing this module never reads settings or
touches the network (tests import it freely).
"""

from __future__ import annotations

from typing import Any

from app.api.app import create_app
from app.config import Settings, get_settings
from app.db.sql import SqlStore, make_engine
from app.engine.graph import build_graph, verify
from app.engine.nodes import Deps
from app.engine.providers import build_fetcher, build_llm, build_search
from app.logging import setup_logging
from app.schemas.verification import VerificationRequest, VerificationResult
from app.services.verification_service import VerificationService


def build_service(settings: Settings) -> VerificationService:
    """Wire real providers, the LangGraph graph and the database into one service."""
    deps = Deps(
        llm=build_llm(settings),
        search=build_search(settings),
        fetcher=build_fetcher(settings),
    )
    graph = build_graph(deps)

    async def run(request: VerificationRequest, result_id: str) -> VerificationResult:
        return await verify(graph, deps, request, result_id=result_id)

    store = SqlStore(make_engine(settings.database_url))
    store.create_tables()
    return VerificationService(
        store, run, clock=deps.clock, max_concurrent=settings.max_concurrent_verifications
    )


def create_default_app() -> Any:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    return create_app(build_service(settings), settings)


def __getattr__(name: str) -> Any:
    if name == "app":
        application = create_default_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)