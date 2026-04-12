"""ChromaDB wrapper — persistent, on-disk vector store for the RAG Generator."""

from __future__ import annotations

import os
from typing import List, Optional

import chromadb
from chromadb.config import Settings


DEFAULT_PERSIST_DIR = os.getenv(
    "SENTINEL_CHROMA_DIR",
    os.path.join(os.path.dirname(__file__), "chroma_store"),
)


def get_chroma_client(persist_dir: str = DEFAULT_PERSIST_DIR) -> chromadb.PersistentClient:
    os.makedirs(persist_dir, exist_ok=True)
    return chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )


def get_or_create_collection(name: str = "source_code"):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)


def query_source_context(query: str, n_results: int = 5, collection_name: str = "source_code") -> List[str]:
    collection = get_or_create_collection(collection_name)
    result = collection.query(query_texts=[query], n_results=n_results)
    docs: Optional[List[List[str]]] = result.get("documents")
    if not docs or not docs[0]:
        return []
    return docs[0]
