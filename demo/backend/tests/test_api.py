"""API tests with the Gemini graph replaced by a fake (no network, no API key needed)."""
from fastapi.testclient import TestClient

import app.main as main


def fake_answer(question, history=None):
    return {"answer": "The latest stable version of Python is 3.9.",
            "sources": [{"title": "Python Release Notes", "last_updated": "2021-10-05"}]}


def test_chat_then_badge(monkeypatch):
    monkeypatch.setattr(main, "answer_question", fake_answer)
    client = TestClient(main.app)

    r = client.post("/chat", json={"message": "What is the latest stable version of Python?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"].startswith("The latest stable")
    assert body["conversation_id"] and body["message_id"]

    badge = client.get(f"/messages/{body['message_id']}/badge").json()
    assert badge["state"] == "stale"
    assert badge["suggested_correction"]


def test_history_is_kept_per_conversation(monkeypatch):
    seen = []

    def spy(question, history=None):
        seen.append(list(history or []))
        return fake_answer(question)

    monkeypatch.setattr(main, "answer_question", spy)
    client = TestClient(main.app)
    first = client.post("/chat", json={"message": "hello"}).json()
    client.post("/chat", json={"message": "again", "conversation_id": first["conversation_id"]})
    assert seen[0] == []
    assert len(seen[1]) == 2


def test_validation_and_404(monkeypatch):
    client = TestClient(main.app)
    assert client.post("/chat", json={"message": ""}).status_code == 422
    assert client.get("/messages/unknown/badge").status_code == 404


def test_generation_failure_returns_502(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(main, "answer_question", boom)
    client = TestClient(main.app)
    assert client.post("/chat", json={"message": "hi"}).status_code == 502


def test_health():
    assert TestClient(main.app).get("/health").json()["status"] == "ok"


def test_freshguard_status_in_mock_mode():
    body = TestClient(main.app).get("/freshguard/status").json()
    assert body["mode"] == "mock"
    assert body["reachable"] is True and body["authenticated"] is True
