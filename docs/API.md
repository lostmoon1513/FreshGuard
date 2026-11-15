# API reference

The full, example-driven contract is in [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) (sections 3–5).
This file is the short index. FastAPI also serves interactive docs at `/docs` and the OpenAPI
schema at `/openapi.json`.

| Method | Path | Auth | Success | Notes |
|---|---|---|---|---|
| GET | `/health` | no | 200 | liveness |
| POST | `/v1/verifications` | key | 202 (200 with `?wait=true` when finished) | body: question, answer, answer_generated_at?, metadata? |
| GET | `/v1/verifications/{id}` | key | 200 | 404 `not_found` |
| GET | `/v1/verifications` | key | 200 | `limit` 1–100, `label`, `before` (cursor) |

Errors: `{"error": {"code", "message"}}` with codes `unauthorized` 401, `not_found` 404,
`validation_error` 422, `rate_limited` 429 (+ `Retry-After`), `internal_error` 500.

Code map: `app/api/` (routes, auth, rate limit, errors) -> `app/services/` (job lifecycle) ->
`app/engine/` (verification) and `app/db/` (storage).

## POST /v1/verifications/{id}/reverify
Checks the same question and answer again, as a NEW verification (the old one is kept, so you
get a history). Same options and responses as `POST /v1/verifications`: `202 {"id","status"}`,
or with `?wait=true&timeout=1..120` the finished result with `200`.
The new result's `metadata` is the original metadata plus `reverified_from` = the original id.
Unknown id: `404 {"error":{"code":"not_found",...}}`. Needs the `X-API-Key` header. Counted by the
rate limit like a submit.

Use it for TTL re-checks: an answer that was `fresh` last week may be `stale` today.
SDK: `fg.reverify(id)` then `fg.wait(new.id)`.

## GET /dashboard
A human-facing page (no API key needed to load it; it asks for the key and then calls `/v1`).
Lists recent results with label, confidence and age, shows claims and quoted evidence with links,
and has buttons to check a new answer and to re-verify.

Note: `GET /v1/verifications` and `GET /v1/verifications/{id}` also include `question`, `answer`
and `answer_generated_at` alongside the result fields.