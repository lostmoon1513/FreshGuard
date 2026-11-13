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