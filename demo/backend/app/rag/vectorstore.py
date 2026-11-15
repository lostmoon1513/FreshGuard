"""Chroma vector store + ingestion (chunk -> embed -> store)."""
import logging
from functools import lru_cache

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings
from app.kb.documents import KB_DOCUMENTS

log = logging.getLogger(__name__)
COLLECTION = "freshguard_demo_kb"


def _embedding_model_name() -> str:
    name = settings.gemini_embedding_model
    return name if name.startswith("models/") else f"models/{name}"


@lru_cache
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=_embedding_model_name(),
        google_api_key=settings.google_api_key,
    )


@lru_cache
def _raw_store() -> Chroma:
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=settings.chroma_dir,
    )


def build_documents() -> list[Document]:
    """Turn the seed KB into chunked LangChain Documents carrying metadata."""
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=80)
    chunks: list[Document] = []
    for item in KB_DOCUMENTS:
        base = Document(
            page_content=item["text"],
            metadata={
                "doc_id": item["id"],
                "title": item["title"],
                "last_updated": item["last_updated"],
                "topic": item["topic"],
            },
        )
        chunks.extend(splitter.split_documents([base]))
    return chunks


def ingest(reset: bool = False) -> int:
    """Embed and store the KB. Returns number of chunks stored."""
    store = _raw_store()
    if reset:
        store.delete_collection()
        _raw_store.cache_clear()
        store = _raw_store()
    chunks = build_documents()
    ids = [f"{c.metadata['doc_id']}-{i}" for i, c in enumerate(chunks)]
    store.add_documents(chunks, ids=ids)  # same ids => upsert, safe to re-run
    log.info("Ingested %d chunks", len(chunks))
    return len(chunks)


def get_vectorstore() -> Chroma:
    """Return the store, ingesting the seed KB the first time it is empty."""
    store = _raw_store()
    if store._collection.count() == 0:
        ingest()
    return store
