"""Loads the persisted Chroma index built by ingest.py and exposes it as a
LangChain retriever. Raises FileNotFoundError with a clear message if
ingest.py hasn't been run yet, rather than silently returning an empty
index."""
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

ROOT = Path(__file__).resolve().parent.parent.parent
PERSIST_DIR = ROOT / "data" / "RAG" / "chroma"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def load_retriever(k: int = 4):
    if not PERSIST_DIR.exists():
        raise FileNotFoundError(
            f"{PERSIST_DIR} not found — run `python3 app/rag/ingest.py` first to build the RAG index."
        )
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    store = Chroma(persist_directory=str(PERSIST_DIR), embedding_function=embeddings)
    return store.as_retriever(search_kwargs={"k": k})
