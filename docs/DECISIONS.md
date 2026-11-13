# Decisions log

Short record of architectural choices and the reason for each. Add a new entry
whenever a decision changes the architecture or a contract.

## D1: LangGraph orchestrates verification
The workflow has conditional routing (skip static claims), a bounded retry loop
(reformulate a failed search once) and per-claim fan-out. That is real graph
behavior, so we use LangGraph rather than a hand-written pipeline.
Nodes may be `async def`; FastAPI is async and search/LLM calls are I/O-bound.

## D2: `engine/` is isolated from `api/` and `db/`
The engine takes `(question, answer)` and returns a result. It does not know how it
was called or where results are stored. This keeps it testable without a database,
a web server or paid APIs. Enforced by `tests/unit/test_architecture.py`.

## D3: LLM and search are interfaces; fakes are test-only
Real providers are chosen by config (`LLM_PROVIDER`, `SEARCH_PROVIDER`).
`fake` is rejected when `ENVIRONMENT=production`.

## D4: An answer with no extractable claims is `unverifiable`
Nothing was checked, so we do not claim `fresh`.

## D5: A stance needs a quote
Evidence marked `supports` or `contradicts` must carry a quoted span. Later, the
integrity check drops any quote that is not a verbatim substring of the fetched page.

## D6: Answer-level label is the worst claim-level label
Severity order: `stale` > `potentially_stale` > `unverifiable` > `fresh`.

## D7: Provider defaults are the real providers
Defaults are `gemini` and `tavily`, so a missing key fails loudly at startup instead
of silently running with fakes.

## D8: Claim labels come from a decision table, not from a score
`app/engine/rules/decision.py` holds one ordered table (see `docs/RULES.md`). Scores only
express confidence in the label the table chose. A weighted sum would let many weak sources
outvote one credible source, which is the failure we are built to prevent.

## D9: Only verified, credible, recent evidence is decisive
"Verified" = stance is supports/contradicts and `integrity_ok is True`. "Strong" = verified,
tier 1-2, inside the freshness window. FRESH and STALE both require strong evidence. Everything
else (tier 3, old, undated) can only produce POTENTIALLY_STALE; no verified evidence at all
produces UNVERIFIABLE. Undated evidence is never assumed recent.

## D10: Credible sources that conflict give POTENTIALLY_STALE
We do not adjudicate between two credible, recent sources that disagree. A human decides.

## D11: Static claims are not searched and are labelled FRESH (confidence 0.5)
This trusts the volatility classifier. A claim misclassified as static will be a false FRESH;
the M7 benchmark must measure this. Static claims with verified evidence are decided by the
same table, with no time limit.

## D12: Freshness windows: fast = 30 days, slow = 365 days
Provisional defaults in `FreshnessPolicy`, to be tuned on the M7 benchmark. A per-claim
override is supported.

## D13: Source tiers are by domain only
Government, academic and intergovernmental domains and a short list of standards bodies are
tier 1; a short list of major news and reference sites is tier 2; everything else is tier 3.
Vendor domains can be promoted per claim via `extra_tier1_domains`. Known limitation: a student
page on a university host is still tier 1.

## D14: Provider APIs are called over plain REST through a tiny `HttpClient` interface
No vendor SDKs. Each provider is a few dozen lines of request/response mapping on top of
`httpx` (already in the stack). `app/engine/providers/httpx_client.py` is the only module that
imports `httpx`; everything else is tested with a scripted fake client, no network.

## D15: Structured LLM output = schema in the prompt + strict Pydantic validation
We do not use vendor-specific structured-output modes. Gemini's `generateContent` is now marked
"Legacy" and its JSON-mode field names changed, so relying on them risks every call failing.
Invalid output raises `LLMOutputError`; it is never repaired or guessed.

## D16: Fallback with cooldown
If the other real provider's key is set it is wired in automatically (Gemini -> Groq,
Tavily -> Serper). After a rate-limit, quota, auth or availability failure the primary is skipped
for 60 s so free-tier quota and latency are protected. One bad LLM reply starts no cooldown.

## D17: Search cache is short-lived, in-memory and single-flight
Default TTL 6 h (`SEARCH_CACHE_TTL_SECONDS`, 0 disables): a long TTL would hide fresh changes,
which defeats freshness monitoring. Empty results and errors are never cached. Concurrent
identical queries (per-claim fan-out) make one provider call. The cache is lost on restart;
a persistent cache can implement the `SearchCache` protocol in M5.

## D18: Relative dates are read conservatively
"3 days ago" is converted relative to the retrieval time. Coarse units ("N months/years ago")
assume the older end (N+1 units), so evidence can look older than it is, never newer.
Unreadable dates become `None` (undated), never a guess (see D9).

## D19: Serper results are snippet-only (open question for M3)
Tavily returns page text (`content`), so quotes can be verified against it. Serper returns only
a short snippet. M3 must decide whether snippet text counts as a "fetched page" for the quote
integrity check, or whether a page fetcher is needed for the Serper fallback.

## D20: LangChain is used as adapters behind our own provider interfaces
Decision by the project owner: use LangChain. `LangChainLLM` wraps any LangChain chat model
(`ChatGoogleGenerativeAI`, `ChatGroq`); `LangChainTavilySearch` / `LangChainSerperSearch` wrap the
LangChain Tavily tool and Serper wrapper. They implement the same `LLMProvider` / `SearchProvider`
as the REST providers, so graph nodes, fakes, fallback and cache do not change. Only
`langchain_backend.py` imports LangChain packages, lazily (enforced by `test_architecture.py`).
`PROVIDER_BACKEND=langchain` (default) or `rest` (tested backup) selects the backend.
Trade-offs accepted: heavier dependencies, and LangChain's Tavily wrapper may drop
`published_date` (hits are then undated, never guessed). Compare with
`scripts/smoke_providers.py`.

## D21: LangGraph is a declared dependency from now
The verification graph is built in M4 with LangGraph (D1). The dependency is declared early so
the smoke script can confirm it installs and imports on every machine before M3/M4 depend on it.

## D22: The LangChain path keeps "schema in prompt + strict Pydantic validation"
We rely on exactly one LangChain call, `ainvoke`, plus the message `.content`. We do not use
`with_structured_output`: its options differ per integration and could not be verified offline.
Our `LLMOutputError` contract and error mapping (`langchain_errors.py`) stay identical to the
REST path. Revisit native structured output once the smoke test proves the base path.
LangChain handles retries and timeouts itself (`max_retries`, `timeout` from settings).
Gemini temperature is left at the library default (Google advises against lowering it for
Gemini 3+).

## D23: A real page fetcher resolves D19 (snippet-only evidence)
Serper returns snippets and Tavily returns no publish dates. Quotes must come from page text and
freshness needs dates, so `HttpPageFetcher` downloads pages for credible (tier 1-2) hits that
lack text, or are undated on a time-sensitive claim. It reads JSON-LD / meta `datePublished`
(never "modified"). SSRF guards: http(s) only, no IP literals or private/loopback/link-local
hosts, blocked suffixes, DNS check, every redirect re-checked, size and time caps, text types
only. Known limits: DNS-rebinding race between check and connect; robots.txt not consulted.
Snippet-only hits that cannot be fetched are dropped: too thin to quote.

## D24: Claims must be grounded in the answer
The LLM must return an `answer_span` copied from the answer. Claims whose span is not a
(whitespace-normalised) substring are dropped, so the checker cannot invent claims.

## D25: Volatility guard can only raise sensitivity
Static -> slow on time cues or recent years; slow -> fast on strong fast cues. A missing or failed
classification defaults to SLOW (searched), never STATIC. Window overrides are clamped to 1..3650.

## D26: Quote integrity
Both sides are normalised (whitespace, curly quotes, dashes) then compared case-sensitively.
Quotes must be 20-600 chars, >= 4 words and contain no ellipsis. Failures are discarded and logged.
Quote-less supports/contradicts and off-topic passages become neutral before they reach the rules.

## D27: Failure semantics
Extraction failure fails the run. Volatility/query-generation failure degrades (slow, claim text
as query). If every searchable claim hit a provider outage and found nothing, the run is FAILED,
not UNVERIFIABLE: "we could not check" differs from "nothing found". Reformulation happens once.

## D28: Corrections are grounded or absent
A suggested correction is kept only for STALE claims, and only if every number and capitalised
name in it appears in the cited verified quote or the original claim.

## D29: Graph logic lives in plain functions; langgraph is imported only in `graph/builder.py`
`graph/steps.py` holds every node and router as ordinary async code (unit-testable without the
library); `builder.py` only registers them, importing langgraph lazily inside `build_graph`.
The architecture test now allows langgraph in that one file and checks the import is lazy.

## D30: Parallelism is inside nodes, not LangGraph `Send`
Each step runs its claims concurrently with `asyncio.gather`, bounded by the semaphores in `Deps`.
Same speed-up, simpler state (one list of claims), and no dependence on `Send` details we could
not verify offline. Revisit if we want per-claim streaming in the dashboard.

## D31: `verify()` never raises
It returns COMPLETED, or FAILED with a generic message; internal errors go to the log only.
Tests run against a tiny stand-in for `langgraph.graph` (always) and the real library (when
installed), so our wiring is checked even on machines without it.

## D32: Verification runs as an in-process background job
`POST` stores a `pending` record and returns at once; an asyncio task runs the graph behind a
semaphore (`MAX_CONCURRENT_VERIFICATIONS`, default 2, to respect free-tier quotas). `?wait=true`
waits up to `timeout` seconds. Jobs interrupted by a restart are marked FAILED at startup
(`recover`) and on shutdown, so nothing stays "running" forever. No Celery/Redis: one process is
enough for the demo; the store interface lets us move to a real queue later.

## D33: One JSON table, `create_all`, no Alembic yet
Each verification is one row: full request and result as JSON plus plain columns for status,
label and ordering (`created_us`, epoch microseconds, avoids SQLite timezone loss). Tables are
created at startup. AGENTS.md lists Alembic; migrations are deferred to M10 because the schema is
still moving and a single table is easy to rebuild. PostgreSQL uses the psycopg 3 driver
(`postgresql://` URLs are rewritten to `postgresql+psycopg://`).

## D34: Layering and API conventions
`schemas <- db`, `engine`, `services <- api`. Tests enforce: engine imports no api/db/services;
db imports only schemas; services import neither api, sqlalchemy nor fastapi. One error format
everywhere; auth is a constant-time API-key check (off only in development when no key is set;
required in production); in-memory rate limiting is per process; `created_at` is the submission
time; internal exception text never reaches clients.

## D35: `app.main:app` is built lazily
A module-level `__getattr__` builds the app on first access, so `uvicorn app.main:app` works while
importing the module (tests) never reads settings or touches providers.