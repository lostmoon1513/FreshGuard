# FreshGuard Integration Guide (API contract v1)

> **Status:** the verification engine (M0–M4), the HTTP API (**M5**) and the Python SDK (**M6**)
> are built. Code against this document; any change to it will be announced.
> Sections marked *(later)* arrive in M8.

## 1. What FreshGuard does

You send it a question and the answer your AI app gave. FreshGuard checks the answer's factual
claims against current web sources and returns one label:

| label | meaning | what your app should do |
|---|---|---|
| `fresh` | credible, recent sources support every claim | show normally |
| `stale` | a credible, recent source contradicts a claim | warn the user; show `suggested_correction` |
| `potentially_stale` | sources conflict, or only weak/old/undated evidence | show a "may be out of date" notice |
| `unverifiable` | not enough verified evidence | show a neutral "could not verify" note; never treat as fresh |

The answer label is the worst claim label (`stale` > `potentially_stale` > `unverifiable` >
`fresh`). Every `stale`/`fresh` verdict is backed by a quote copied verbatim from a fetched page.

## 2. Important: verification is slow

Free-tier LLMs and live web search mean **10–60 seconds per answer**. Do not make your chat
reply wait for it. Recommended pattern: reply to the user immediately, verify in the background,
then update a badge on that message (section 7).

## 3. Running the backend

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```
Base URL in development: `http://localhost:8000`. Interactive docs: `http://localhost:8000/docs`.
Needs the keys in `backend/.env` (Gemini/Groq, Tavily/Serper). Set `FRESHGUARD_API_KEY=<any secret>`
to require authentication; if unset in development, auth is off (production refuses to start
without it). Quick live check once the server is running: `python scripts/smoke_api.py`.
Every response carries an `X-Request-ID` header; send your own (letters, digits, `. _ -`, max 64)
to correlate logs. Default rate limit: 30 submissions per minute per key and client address.

## 4. REST API

All bodies are JSON (`Content-Type: application/json`). Timestamps are ISO-8601 with timezone.
Auth: header `X-API-Key: <FRESHGUARD_API_KEY>` on every `/v1/*` call.

### GET /health
`200 {"status": "ok"}`. No auth. Use it to check the server is up.

### POST /v1/verifications — submit an answer
Request:
```json
{
  "question": "Who is the CEO of Acme Corp?",
  "answer": "Jon Lee is the chief executive of Acme Corp.",
  "answer_generated_at": "2026-11-13T09:00:00+05:30",
  "metadata": {"conversation_id": "c-42", "message_id": "m-7"}
}
```
- `question`: 1–2000 chars. `answer`: 1–20000 chars. Both required.
- `answer_generated_at`: optional. `metadata`: optional object of strings, stored and returned
  as-is (use it to link the result to your chat message).

Default (asynchronous): **`202 Accepted`**
```json
{"id": "9f1c...", "status": "pending"}
```
Blocking variant: `POST /v1/verifications?wait=true&timeout=60` returns **`200`** with the
full result below if it finishes within `timeout` seconds (1–120, default 60); otherwise `202`
with the current status, and you poll.

### GET /v1/verifications/{id} — fetch a result
`200` with the object below, `404` if unknown. Poll every 2 seconds until `status` is
`completed` or `failed`.

```json
{
  "id": "9f1c...",
  "status": "completed",
  "label": "stale",
  "confidence": 0.81,
  "suggested_correction": "Priya Raman is the chief executive of Acme Corp.",
  "error": null,
  "created_at": "2026-11-13T03:30:00Z",
  "finished_at": "2026-11-13T03:30:24Z",
  "metadata": {"conversation_id": "c-42", "message_id": "m-7"},
  "claims": [
    {
      "text": "Jon Lee is the chief executive of Acme Corp",
      "volatility": "slow",
      "label": "stale",
      "reasoning": "A credible, recent source contradicts the claim (0 supporting, 1 contradicting verified source(s)).",
      "freshness_window_days": 365,
      "evidence": [
        {
          "url": "https://www.reuters.com/acme",
          "tier": 2,
          "published_at": "2026-02-20T00:00:00Z",
          "fetched_at": "2026-11-13T03:30:12Z",
          "stance": "contradicts",
          "quoted_span": "Priya Raman was appointed chief executive of Acme Corp",
          "integrity_ok": true
        }
      ]
    }
  ]
}
```
Field notes:
- `status`: `pending` | `running` | `completed` | `failed`. `label`/`confidence` are `null`
  unless `completed`. A `failed` run means we *could not check* (providers down), which is
  different from `unverifiable`; `error` explains in plain words. Retry later.
- `confidence`: 0–1. `unverifiable` is always 0. `potentially_stale` never exceeds 0.5.
- `suggested_correction`: only present when `label` is `stale`.
- `tier`: 1 official/primary, 2 reputable secondary, 3 other. `stance`: `supports` |
  `contradicts` | `neutral`. `published_at` may be `null` (undated pages).
- `claims` can be empty (nothing checkable found); the label is then `unverifiable`.

### GET /v1/verifications — list (for dashboards)
Query: `limit` (1–100, default 20), `label` (optional filter), `before` (an id, for paging).
`200 {"items": [<result>...], "next_before": "<id>|null"}`

### Errors
Every error has this shape:
```json
{"error": {"code": "validation_error", "message": "answer: String should have at least 1 character"}}
```
| HTTP | code | when |
|---|---|---|
| 401 | `unauthorized` | missing/wrong `X-API-Key` |
| 404 | `not_found` | unknown id |
| 422 | `validation_error` | bad body (empty or too long text) |
| 429 | `rate_limited` | too many requests; honour `Retry-After` |
| 500 | `internal_error` | our bug; safe to retry once |

## 5. curl examples (PowerShell: use `curl.exe`)
```powershell
curl.exe -X POST "http://localhost:8000/v1/verifications" `
  -H "X-API-Key: dev-key" -H "Content-Type: application/json" `
  -d '{\"question\":\"Who is the CEO of Acme Corp?\",\"answer\":\"Jon Lee is the chief executive of Acme Corp.\"}'

curl.exe -H "X-API-Key: dev-key" "http://localhost:8000/v1/verifications/<id>"
```

## 6. Python SDK

Install from the repo root (editable): `pip install -e ./sdk` — package name `freshguard`
(Python 3.9+). More detail and runnable examples: `sdk/README.md`, `sdk/examples/`.
It is a thin HTTP client (httpx); it contains no verification logic.

```python
from freshguard import FreshGuard

fg = FreshGuard(base_url="http://localhost:8000", api_key="dev-key", timeout=30.0)

# Simplest: block until done (up to wait_seconds), returns a Verification
v = fg.verify(question="Who is the CEO of Acme Corp?",
              answer="Jon Lee is the chief executive of Acme Corp.",
              wait_seconds=90)
print(v.label)                  # "stale"
print(v.confidence)             # 0.81
print(v.suggested_correction)   # "Priya Raman is ..."
print(v.should_warn)            # True for stale / potentially_stale
for claim in v.claims:
    print(claim.label, claim.text)
    for ev in claim.evidence:
        print("  ", ev.stance, ev.url, ev.quoted_span)
```

Non-blocking (recommended for chat):
```python
job = fg.submit(question=q, answer=a, metadata={"message_id": "m-7"})   # returns at once
...                                  # later, e.g. a background task or the next UI poll
v = fg.get(job.id)                   # v.status in {"pending","running","completed","failed"}
v = fg.wait(job.id, timeout=90)      # blocks, polling every 2 s
```

Async version (FastAPI / async bots): `from freshguard import AsyncFreshGuard`, same methods
with `await`, and `async with AsyncFreshGuard(...) as fg:`.

`Verification` fields: `id, status, label, confidence, suggested_correction, error, claims,
created_at, finished_at, metadata`, plus helpers `is_done`, `is_stale`, `should_warn`.
`label` is a plain string from the four values in section 1.

Exceptions (all subclass `FreshGuardError`): `AuthError` (401), `NotFoundError` (404),
`ValidationError` (422), `RateLimitError` (429, has `.retry_after`), `ServerError` (5xx),
`VerificationTimeout` (wait ran out; the job keeps running, call `get`/`wait` again),
`ConnectionFailed`. Reads (`get`, `wait`, `list`) are retried twice on network errors and 5xx;
`submit` and `verify` are never retried, because a retry could create a duplicate job. A job that
finished but could not be checked is *returned* with `status == "failed"` and `.error`, not raised.
Wrap calls so FreshGuard
being down never breaks your chatbot:
```python
try:
    v = fg.verify(question=q, answer=a, wait_seconds=60)
except FreshGuardError:
    v = None          # show the answer without a badge
```

## 7. How the demo RAG chatbot should use it

1. User asks a question; the bot answers from its knowledge base (RAG) as usual.
2. Send the answer to the user immediately.
3. In the background call `fg.submit(question, answer, metadata={"message_id": ...})` and store
   `job.id` with the message.
4. The UI polls `GET /v1/verifications/{id}` (or your own endpoint wrapping `fg.get`) every 2 s
   and shows a badge on that message:

| label | badge | text |
|---|---|---|
| `fresh` | green | "Verified current" |
| `stale` | red | "Out of date" + show `suggested_correction` and the first evidence `url` |
| `potentially_stale` | amber | "May be out of date" |
| `unverifiable` | grey | "Could not verify" |
| status `failed` / still running | none / spinner | "Checking…" / hide badge |

5. Make the demo convincing: seed the bot's knowledge base with a **deliberately outdated**
   document (for example, a company's old CEO or an old product price) so the bot answers
   confidently with a stale fact, and FreshGuard catches it live.
6. *(later, M8)* **TTL re-verification:** store each answer with `verified_at`; a scheduled job
   re-submits answers older than their window (fast claims ~30 days, slow ~365) and flips
   badges if a fact changed. A `POST /v1/verifications/{id}/reverify` endpoint will be added.

## 8. Limits and guarantees

- Up to 8 claims are checked per answer; extra claims are ignored.
- Search results are cached for 6 hours, so repeating the same answer within that time is faster.
- FreshGuard never guesses: no verified evidence means `unverifiable`.
- Evidence quotes are always verbatim text from the cited page; unverifiable quotes are dropped.
- Rate limits and quotas depend on the free-tier providers; expect occasional `failed` runs.

## 9. Not in v1
Streaming results, webhooks, multi-tenant accounts, non-English answers, images. Auth is a single
shared API key, which is enough for the demo but not for public deployment.