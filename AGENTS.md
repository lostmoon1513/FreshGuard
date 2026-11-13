# FreshGuard: Instructions for AI Coding Agents

FreshGuard is a stale-answer detection and freshness monitoring platform for AI apps.
Treat this file and the FreshGuard Project Blueprint as the specification.

## Non-negotiables
1. Never invent verification results or fabricate evidence.
2. Every evidence quote must be a verbatim substring of a document the system fetched.
   If it is not, discard it and log the failure.
3. Labels are exactly: `fresh`, `stale`, `potentially_stale`, `unverifiable`.
   When evidence is insufficient, return `unverifiable`.
4. LLMs do structured extraction and semantic comparison only.
   Scoring, source validation and the final label are deterministic code.
5. The SDK is a thin HTTP client. All verification logic lives in the backend.
6. `app/engine/` must never import from `app/api/` or `app/db/`.
   (Enforced by `tests/unit/test_architecture.py`.)
7. Fake providers exist for tests only. They must never run in production
   (enforced by `Settings` validation) and never be presented as real results.

## Stack
- Backend and SDK: Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy, Alembic, httpx, pytest.
- Orchestration: LangGraph (the verification workflow is a LangGraph graph).
- Database: PostgreSQL in production, SQLite allowed for local tests.
- Dashboard (later): JavaScript, React, Tailwind CSS.
- No new technology without a written reason in `docs/DECISIONS.md`.

## Priority order
1. Core verification engine  2. FastAPI backend  3. Python SDK
4. Integration tests and benchmark  5. Minimal dashboard (after the end-to-end test passes)
6. Deployment and demo chatbot  7. Polish

## Before implementing a module
State its responsibility, inputs, outputs, dependencies and interface,
and check compatibility with existing modules.

## When modifying code
Inspect the current implementation first. Preserve working behavior.
Avoid unnecessary rewrites. Add or update tests.
Update `docs/API.md` when an API contract changes. Explain architectural changes.

## Quality bar
- Validate all inputs. Use one consistent error format.
- Log with request IDs. Never log secrets.
- Cover decision rules with exhaustive unit tests.
- Do not claim a feature is complete until it is implemented and tested.

## Per task, report
What is being built, why, which files change, how it works,
how it is tested, and what remains.
