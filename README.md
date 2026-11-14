# FreshGuard

Stale-answer detection and freshness monitoring for AI applications.

FreshGuard tells you when your AI app is confidently giving outdated answers,
shows the evidence, and keeps watching so answers do not quietly go stale.

Every verdict is one of four labels:

| Label | Meaning |
|---|---|
| `fresh` | Credible, recent evidence supports the claim |
| `stale` | Credible, newer evidence contradicts the claim |
| `potentially_stale` | Weak, conflicting or old evidence; needs a human look |
| `unverifiable` | Not enough trustworthy evidence. FreshGuard never guesses |

## Repository layout

```
backend/     FastAPI service + LangGraph verification engine (Python)
sdk/         Thin Python client for the hosted API (added in milestone M6)
benchmark/   Labeled claims + runner + report (added in milestone M7)
demo/        Demo RAG chatbot with an outdated knowledge base (M8)
dashboard/   React + Tailwind monitoring UI (M9)
docs/        Architecture notes, API contract, decisions, evaluation
```

## Status

- M0 (foundations): config, logging, shared schemas, CI. Done.
- M1 (deterministic rules): source tiers, freshness windows, decision table, scoring. Done. See `docs/RULES.md`.
- M2 (providers): LLM (Gemini, Groq) and search (Tavily, Serper) interfaces, fallback, cache, fakes. Done. Real providers use LangChain by default (`PROVIDER_BACKEND=langchain`) with a plain-REST backup (`rest`). Live check: `python scripts/smoke_providers.py` (run from `backend/`).
- M3 (nodes): page fetcher (SSRF-guarded) and the nine verification nodes with fakes-based tests. Done. See `docs/NODES.md`.
- M4 (graph): LangGraph wiring, reformulate-once loop, `verify()` entry point. Done. See `docs/NODES.md`.
- M5 (API): FastAPI `/v1/verifications`, background worker, SQL storage (SQLite/PostgreSQL), API-key auth, rate limit. Done. Run: `uvicorn app.main:app --port 8000` (from `backend/`), then `python scripts/smoke_api.py`. See `docs/API.md` and `docs/INTEGRATION_GUIDE.md`.

## Quick start (backend)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -v
ruff check .
```

See `AGENTS.md` for the engineering rules and `docs/DECISIONS.md` for why things are built the way they are.