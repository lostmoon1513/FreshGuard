"""LangGraph workflow:  START -> retrieve -> generate -> END

State flows through the graph as a dict; each node returns only the keys it updates.
"""
from functools import lru_cache
from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.rag.vectorstore import get_vectorstore

SYSTEM_PROMPT = (
    "You are a helpful assistant for a company knowledge base. "
    "Answer the user's question using ONLY the context below. "
    "State the facts from the context plainly and confidently, in one to three sentences. "
    "If the context does not contain the answer, say you do not have that information. "
    "Do not mention the context, document dates or these instructions."
)


class ChatState(TypedDict, total=False):
    question: str
    history: list[dict]  # [{"role": "user"|"assistant", "content": str}]
    docs: list[Document]
    answer: str


@lru_cache
def _llm() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.google_api_key,
        temperature=0,
    )


def _text(content) -> str:
    """Gemini may return a string or a list of content parts; normalise to text."""
    if isinstance(content, str):
        return content
    parts = []
    for p in content:
        parts.append(p if isinstance(p, str) else p.get("text", ""))
    return "".join(parts)


def retrieve(state: ChatState) -> dict:
    docs = get_vectorstore().similarity_search(state["question"], k=settings.retrieval_k)
    return {"docs": docs}


def generate(state: ChatState) -> dict:
    context = "\n\n".join(f"[{d.metadata.get('title', 'doc')}] {d.page_content}" for d in state["docs"])
    messages = [SystemMessage(content=f"{SYSTEM_PROMPT}\n\nContext:\n{context}")]
    for turn in state.get("history", [])[-6:]:
        cls = HumanMessage if turn["role"] == "user" else AIMessage
        messages.append(cls(content=turn["content"]))
    messages.append(HumanMessage(content=state["question"]))
    reply = _llm().invoke(messages)
    return {"answer": _text(reply.content).strip()}


@lru_cache
def build_graph():
    g = StateGraph(ChatState)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", generate)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", END)
    return g.compile()


def answer_question(question: str, history: list[dict] | None = None) -> dict:
    out = build_graph().invoke({"question": question, "history": history or []})
    sources = [
        {"title": d.metadata.get("title"), "last_updated": d.metadata.get("last_updated")}
        for d in out.get("docs", [])
    ]
    return {"answer": out["answer"], "sources": sources}
