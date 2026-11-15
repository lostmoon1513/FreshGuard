from app.kb.documents import KB_DOCUMENTS
from app.rag.vectorstore import build_documents


def test_kb_has_stale_fresh_and_static_docs():
    expected = {d["expected"] for d in KB_DOCUMENTS}
    assert {"stale", "fresh", "unverifiable", "potentially_stale"} <= expected


def test_chunks_carry_metadata():
    chunks = build_documents()
    assert chunks
    for c in chunks:
        assert c.metadata["title"] and c.metadata["last_updated"] and c.metadata["doc_id"]
