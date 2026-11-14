# Deploying FreshGuard (Render + Neon Postgres)

The API is one Docker container. It needs a Postgres database and four secrets.

## 1. Database (Neon, free)
1. neon.tech > create a project > copy the connection string
   (`postgresql://user:pass@host/dbname?sslmode=require`).
2. That string is `DATABASE_URL`. Tables are created on first start.

## 2. API key for your own clients
Make a long random value, e.g. in PowerShell:
`[guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")`
This is `FRESHGUARD_API_KEY`. The demo bot and the SDK send it as `X-API-Key`.
Production refuses to start without it.

## 3. Render
1. render.com > New > Blueprint > select this repo (it reads `render.yaml`).
2. Fill the secrets: `DATABASE_URL`, `FRESHGUARD_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`,
   `TAVILY_API_KEY`, `FETCH_CONTACT` (your email). `SERPER_API_KEY` is optional.
3. Deploy. First build takes a few minutes. Watch the logs for `Uvicorn running`.
4. Check: open `https://<service>.onrender.com/health` (should return ok).

## 4. Smoke test the live service (from backend/)
    $env:FRESHGUARD_URL="https://<service>.onrender.com"
    $env:FRESHGUARD_API_KEY="<your key>"
    python ../sdk/examples/quickstart.py

## Things to know
- Render's free web service sleeps after ~15 minutes idle; the first request then takes
  30-60 seconds. Open `/health` a few minutes before any demo.
- Jobs run inside the process. A restart marks running jobs failed (they can be resubmitted).
  Keep one instance; do not scale to several.
- Set `CORS_ORIGINS` only if a browser app on another domain calls the API.
- Free-tier model quotas (Gemini, Tavily) apply to the deployed service too.

## Railway instead
New Project > Deploy from GitHub > set Root Directory to `backend`, add a Postgres plugin
(its `DATABASE_URL` is picked up automatically), and add the same variables as above.