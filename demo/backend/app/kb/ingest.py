"""CLI:  python -m app.kb.ingest [--reset]"""
import sys

from app.rag.vectorstore import ingest

if __name__ == "__main__":
    n = ingest(reset="--reset" in sys.argv)
    print(f"Stored {n} chunks in Chroma.")
