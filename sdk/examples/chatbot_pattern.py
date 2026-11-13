"""How a chatbot should use FreshGuard: answer first, verify in the background, update a badge.

Run:  python examples/chatbot_pattern.py     (backend must be running)

This is a console simulation. In a real web app, replace `show_badge` with an update to your
UI (websocket push, or the browser polling your own endpoint that calls `fg.get`).
"""

import os
import threading

from freshguard import FreshGuard, FreshGuardError, Verification

fg = FreshGuard(
    base_url=os.getenv("FRESHGUARD_URL", "http://localhost:8000"),
    api_key=os.getenv("FRESHGUARD_API_KEY"),
)

BADGES = {
    "fresh": "GREEN  Verified current",
    "stale": "RED    Out of date",
    "potentially_stale": "AMBER  May be out of date",
    "unverifiable": "GREY   Could not verify",
}


def badge_for(result: Verification) -> str:
    if result.status == "failed":
        return "NONE   (check failed; show no badge)"
    text = BADGES.get(result.label or "unverifiable", BADGES["unverifiable"])
    if result.is_stale and result.suggested_correction:
        text += f" - {result.suggested_correction}"
    return text


def show_badge(message_id: str, text: str) -> None:
    print(f"\n[badge for message {message_id}] {text}")


def verify_in_background(message_id: str, question: str, answer: str) -> None:
    def work() -> None:
        try:
            job = fg.submit(question, answer, metadata={"message_id": message_id})
            result = fg.wait(job.id, timeout=150)
            show_badge(message_id, badge_for(result))
        except FreshGuardError as exc:
            show_badge(message_id, f"NONE   (FreshGuard unavailable: {exc})")

    threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    question = "Who is the CEO of Twitter?"
    answer = "Jack Dorsey is the CEO of Twitter."  # imagine this came from your RAG pipeline
    print("BOT:", answer)  # 1) reply to the user immediately
    show_badge("m-1", "...    Checking")  # 2) show a spinner
    verify_in_background("m-1", question, answer)  # 3) verify without blocking the chat
    threading.Event().wait(timeout=170)