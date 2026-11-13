# FreshGuard Python SDK

A thin client for the FreshGuard API. It sends an AI answer to the server, which checks its factual
claims against current web sources and returns `fresh`, `stale`, `potentially_stale` or
`unverifiable`. All verification logic runs on the server.

Full API contract and chatbot integration plan: `docs/INTEGRATION_GUIDE.md`.

## Install

From the repo root, in your app's virtual environment:

```powershell
pip install -e ./sdk
```

Requires Python 3.9+ (installs `httpx`).

## Use

```python
from freshguard import FreshGuard

fg = FreshGuard(base_url="http://localhost:8000", api_key="dev-key")

result = fg.verify(
    question="Who is the CEO of Twitter?",
    answer="Jack Dorsey is the CEO of Twitter.",
    wait_seconds=90,
)
print(result.label, result.confidence)  # "stale" 0.8
print(result.suggested_correction)
print(result.should_warn)  # True for stale / potentially_stale
```

Verification takes 10-60+ seconds, so in a chat app reply first and verify in the background:

```python
job = fg.submit(question, answer, metadata={"message_id": "m-7"})  # returns at once
...
result = fg.get(job.id)  # status: pending | running | completed | failed
result = fg.wait(job.id, timeout=90)  # or block, polling every 2 s
```

See `examples/chatbot_pattern.py`. Async version: `from freshguard import AsyncFreshGuard` with
`async with AsyncFreshGuard(...) as fg:` and `await` on every method.

## Methods

| Method | Does |
|---|---|
| `verify(question, answer, wait_seconds=60, metadata=None)` | submit and wait; returns the result, or raises `VerificationTimeout` |
| `submit(question, answer, metadata=None)` | start a job, returns a `pending` result at once |
| `get(id)` | current state of a job |
| `wait(id, timeout=90, poll_interval=2)` | poll until finished; raises `VerificationTimeout` (job keeps running) |
| `list(limit=20, label=None, before=None)` | recent results, newest first, with paging cursor `next_before` |
| `health()` | `True` if the server is reachable |

A job that finished but could not be checked (providers down) is **returned** with
`status == "failed"` and `.error` set; it is not raised.

## Errors

All subclass `FreshGuardError`: `AuthError` (401), `NotFoundError` (404), `ValidationError`
(422, or a bad argument), `RateLimitError` (429, has `.retry_after`), `ServerError` (5xx),
`ConnectionFailed`, `VerificationTimeout`. Each has `.status`, `.code` and `.request_id` when known.
Reads (`get`, `wait`, `list`) are retried twice on network errors and 5xx; `submit` and `verify` are
never retried, because a retry could create a duplicate job.

```python
try:
    result = fg.verify(question, answer, wait_seconds=60)
except FreshGuardError:
    result = None  # show the answer without a badge
```

## Test

```powershell
cd sdk
pip install -e ".[dev]"
python -m pytest -q
```