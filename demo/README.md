# FreshGuard Demo Chatbot

A RAG chatbot (FastAPI + LangChain + LangGraph + Gemini + Chroma, React UI) whose job is to
**exercise the FreshGuard SDK end to end**. The bot answers from a knowledge base that contains
deliberately outdated documents. The answer is shown immediately; FreshGuard verifies it in the
background and a badge appears on the message.

```
React UI (chat + badges, polls every 2 s)
   |  POST /chat      GET /messages/{id}/badge
FastAPI backend (port 8001)
   |-- LangGraph:  retrieve -> generate           (Gemini + Chroma)
   |-- FreshGuard layer: submit (background) -> poll -> badge
         |-- MockFreshGuard   (default, offline, follows the contract)
         |-- RealFreshGuard   (the repo's `freshguard` SDK, in ../sdk)
```

## Folder map

```
freshguard-chatbot/
├── backend/
│   ├── app/
│   │   ├── config.py            settings from .env (one `settings` object)
│   │   ├── main.py              FastAPI routes: /health /chat /messages/{id}/badge /samples /kb
│   │   ├── schemas.py           request/response models
│   │   ├── kb/
│   │   │   ├── documents.py     seed KB: stale, fresh, static, unverifiable, weak-evidence docs
│   │   │   └── ingest.py        CLI:  python -m app.kb.ingest [--reset]
│   │   ├── rag/
│   │   │   ├── vectorstore.py   Chroma store, chunking, embedding (Gemini), ingestion
│   │   │   └── graph.py         LangGraph: retrieve -> generate
│   │   └── freshguard/
│   │       ├── mock_client.py   fake SDK, same interface as the real one
│   │       ├── real_client.py   adapter over the real `freshguard` SDK
│   │       ├── badges.py        Verification -> badge mapping (guide section 7)
│   │       └── service.py       never-break-chat wrapper, message_id -> job id
│   ├── tests/                   20 tests: every outcome, API, outage handling
│   ├── requirements.txt / requirements-dev.txt / pytest.ini / .env.example
└── frontend/                    Vite + React
    └── src/ App.jsx, api.js, hooks.js (polling), components/{Message,Badge}.jsx, styles.css
```

## Run it (PowerShell)

**Backend**
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env          # then put your GOOGLE_API_KEY in .env
uvicorn app.main:app --reload --port 8001
```
The knowledge base is embedded into Chroma automatically on the first chat
(or run `python -m app.kb.ingest --reset`). Check `http://localhost:8001/health` and `/docs`.

**Frontend** (second terminal)
```powershell
cd frontend
copy .env.example .env
npm install
npm run dev
```
Open http://localhost:5173 and click a sample question.

## Mock vs. real FreshGuard

Default is the mock (`USE_MOCK_FRESHGUARD=true`), so you can demo with no friend's server.
The mock waits `MOCK_DELAY_SECONDS` (default 6) to imitate the real 10-60 s verification.

To switch to the real service (the SDK is in this repo's `sdk/` folder):
```powershell
# terminal 1: the FreshGuard backend on port 8000  (cd backend; uvicorn app.main:app --port 8000)
# terminal 2: this chatbot backend (demo/backend, venv active)
pip install -e ../../sdk
# in demo/backend/.env:
#   USE_MOCK_FRESHGUARD=false
#   FRESHGUARD_BASE_URL=http://localhost:8000
#   FRESHGUARD_API_KEY=<same key as the FreshGuard server>
```
Only `real_client.py` touches the SDK. Nothing else changes.

### Checking that the SDK works

1. **Header pill in the UI** (and `GET /freshguard/status`): `FreshGuard: mock` (grey),
   `FreshGuard: connected` (green), `bad API key` (amber) or `unreachable` (red). In real mode it
   calls the SDK's `health()` plus one authenticated `list()` call, so a wrong key is caught too.
2. **Live script**, no Gemini key needed: `python scripts/check_sdk.py` submits a stale answer
   through the same adapter the chatbot uses, waits for the verdict and prints the label and badge.
3. **Chat itself**: ask "Who is the CEO of Twitter?" and watch the badge go from *Checking…* to red.

While polling, a transient SDK error (network blip, 429, 5xx) keeps the badge on *Checking…*; after
5 failures in a row, or on any other error, the badge is hidden and the chat keeps working.

## Test matrix

| Ask | KB says | Expected badge |
|---|---|---|
| Latest stable Python? | 3.9 (2021) | red, Out of date + correction + source |
| Latest React? | 17 (2021) | red |
| Node LTS? | 16 (2021) | red |
| CEO of Twitter? | Parag Agrawal | red |
| UK Prime Minister? | Boris Johnson | red |
| CEO of Microsoft? | Satya Nadella | green, Verified current |
| Capital of India? | New Delhi | green (no false alarm on static facts) |
| Acme Cloud Pro price? | 49 USD | amber, May be out of date |
| Example University exam date? | 15 Mar 2027 | grey, Could not verify |
| any question containing "simulate failure" (mock) | n/a | no badge, chat keeps working |

Run the automated checks: `cd backend; pip install -r requirements-dev.txt; pytest`
(tests use the mock and a fake LLM, so they need no API key or network).
`tests/test_sdk_integration.py` runs the *real* SDK over a fake HTTP transport; it is skipped unless
the SDK is installed (`pip install -e ../../sdk`).

**Real-FreshGuard caveat:** the mock's verdicts are keyword rules written from the contract.
The real service decides from live web evidence, so some outcomes (e.g. which source it cites, or
whether the Acme pricing doc lands amber or grey) may differ. That is the point of the test.
The stale documents were chosen from facts that have really changed (Python/React/Node releases,
Twitter CEO, UK PM), but the real FreshGuard judges against whatever the web says today.

## Notes

- Model names (`GEMINI_CHAT_MODEL`, `GEMINI_EMBEDDING_MODEL`) live in `.env`; change them if Google renames models.
- Conversation history is in memory and message-to-job mapping too; restarting the backend clears both (fine for a demo).
- Not yet built (contract M8): TTL re-verification and the `reverify` endpoint.
