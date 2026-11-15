import threading
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.freshguard.service import get_service
from app.kb.documents import KB_DOCUMENTS, SAMPLE_QUESTIONS
from app.rag.graph import answer_question
from app.schemas import ChatRequest, ChatResponse

app = FastAPI(title="FreshGuard Demo Chatbot")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

# conversation_id -> list of {"role", "content"}  (in-memory; fine for a demo)
_history: dict[str, list[dict]] = {}
_history_lock = threading.Lock()


@app.get("/health")
def health():
    return {"status": "ok", "mock_freshguard": settings.use_mock_freshguard}


@app.get("/freshguard/status")
def freshguard_status():
    """Is the FreshGuard SDK connected? mode (mock|real), reachable, API key accepted."""
    return get_service().status()


@app.get("/samples")
def samples():
    return {"questions": SAMPLE_QUESTIONS}


@app.get("/kb")
def kb():
    """Show what is in the knowledge base (handy for the demo: reveals which docs are stale)."""
    return [{k: d[k] for k in ("id", "title", "last_updated", "text")} for d in KB_DOCUMENTS]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, background: BackgroundTasks):
    conversation_id = req.conversation_id or str(uuid.uuid4())
    with _history_lock:
        history = list(_history.get(conversation_id, []))

    try:
        result = answer_question(req.message, history)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Answer generation failed: {exc}") from exc

    answer = result["answer"]
    message_id = str(uuid.uuid4())
    with _history_lock:
        turns = _history.setdefault(conversation_id, [])
        turns.append({"role": "user", "content": req.message})
        turns.append({"role": "assistant", "content": answer})

    # Reply NOW; verification happens in the background (it takes 10-60s).
    service = get_service()
    service.start(message_id)
    background.add_task(service.submit, message_id, req.message, answer, conversation_id)

    return ChatResponse(conversation_id=conversation_id, message_id=message_id,
                        answer=answer, sources=result["sources"])


@app.get("/messages/{message_id}/badge")
def message_badge(message_id: str):
    badge = get_service().badge(message_id)
    if badge is None:
        raise HTTPException(status_code=404, detail="unknown message_id")
    return badge
