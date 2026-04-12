"""ChromaDB wrapper — persistent, on-disk vector store for the RAG Generator.

Responsibilities:
- Own the single Chroma client and `source_code` collection.
- Ingest a local source tree (React + FastAPI) into the collection with per-file
  chunking and metadata (path, language, chunk index).
- Serve grounded retrieval to the Generator — each snippet is returned with a
  `[file.path:start-end]` header so the LLM can cite real locations in
  `source_refs` instead of inventing them.

Embedding model: Chroma's default (all-MiniLM-L6-v2) runs locally and is
sufficient for code-symbol retrieval. We deliberately do NOT send embeddings
to a hosted provider even though generation now uses Gemini — the corpus
stays on disk.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import chromadb
from chromadb.config import Settings


DEFAULT_PERSIST_DIR = os.getenv(
    "SENTINEL_CHROMA_DIR",
    os.path.join(os.path.dirname(__file__), "chroma_store"),
)
DEFAULT_COLLECTION = "source_code"

_LANG_BY_EXT: Dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".vue": "vue",
    ".go": "go",
    ".java": "java",
}

# Directories we never index — noise or binary blobs.
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".venv", "venv", "chroma_store", "coverage", ".turbo", ".cache",
}

_MAX_FILE_BYTES = 256 * 1024  # 256 KB — skip giant bundles / lockfiles


@dataclass(frozen=True)
class SourceSnippet:
    text: str
    path: str
    language: str
    start_line: int
    end_line: int

    def as_prompt_block(self) -> str:
        return (
            f"[{self.path}:{self.start_line}-{self.end_line} ({self.language})]\n"
            f"{self.text}"
        )


def get_chroma_client(persist_dir: str = DEFAULT_PERSIST_DIR) -> chromadb.PersistentClient:
    os.makedirs(persist_dir, exist_ok=True)
    return chromadb.PersistentClient(
        path=persist_dir,
        settings=Settings(anonymized_telemetry=False),
    )


def get_or_create_collection(name: str = DEFAULT_COLLECTION):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #

def _chunk_lines(
    lines: List[str],
    chunk_size: int = 80,
    overlap: int = 10,
) -> Iterable[Tuple[int, int, str]]:
    """Yield (start_line, end_line, text) with 1-based inclusive line numbers."""
    if not lines:
        return
    step = max(1, chunk_size - overlap)
    i = 0
    n = len(lines)
    while i < n:
        j = min(n, i + chunk_size)
        yield i + 1, j, "".join(lines[i:j])
        if j == n:
            break
        i += step


def _iter_source_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _LANG_BY_EXT:
                continue
            full = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(full) > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield full


def _doc_id(rel_path: str, start: int, end: int) -> str:
    h = hashlib.sha1(f"{rel_path}:{start}-{end}".encode("utf-8")).hexdigest()[:16]
    return f"{rel_path}:{start}-{end}:{h}"


def ingest_source_tree(
    root: str,
    collection_name: str = DEFAULT_COLLECTION,
    reset: bool = False,
) -> Dict[str, int]:
    """Walk `root`, chunk every source file, and upsert into the collection.

    Returns a summary dict: files_indexed, chunks_written.
    """
    root = os.path.abspath(root)
    client = get_chroma_client()
    if reset:
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
    collection = client.get_or_create_collection(name=collection_name)

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, str]] = []
    files_indexed = 0

    for abs_path in _iter_source_files(root):
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        if not lines:
            continue

        rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
        language = _LANG_BY_EXT[os.path.splitext(abs_path)[1].lower()]
        files_indexed += 1

        for start, end, text in _chunk_lines(lines):
            ids.append(_doc_id(rel_path, start, end))
            docs.append(text)
            metas.append(
                {
                    "path": rel_path,
                    "language": language,
                    "start_line": start,
                    "end_line": end,
                }
            )

        # Flush in batches to keep memory bounded.
        if len(ids) >= 256:
            collection.upsert(ids=ids, documents=docs, metadatas=metas)
            ids.clear(); docs.clear(); metas.clear()

    if ids:
        collection.upsert(ids=ids, documents=docs, metadatas=metas)

    return {"files_indexed": files_indexed, "chunks_written": collection.count()}


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #

def query_source_snippets(
    query: str,
    n_results: int = 5,
    collection_name: str = DEFAULT_COLLECTION,
) -> List[SourceSnippet]:
    collection = get_or_create_collection(collection_name)
    if collection.count() == 0:
        return []

    result = collection.query(query_texts=[query], n_results=n_results)
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]

    snippets: List[SourceSnippet] = []
    for text, meta in zip(docs, metas):
        meta = meta or {}
        snippets.append(
            SourceSnippet(
                text=text,
                path=str(meta.get("path", "unknown")),
                language=str(meta.get("language", "text")),
                start_line=int(meta.get("start_line", 0) or 0),
                end_line=int(meta.get("end_line", 0) or 0),
            )
        )
    return snippets


def query_source_context(
    query: str,
    n_results: int = 5,
    collection_name: str = DEFAULT_COLLECTION,
) -> List[str]:
    """Backward-compatible helper — returns pre-formatted snippet strings."""
    return [s.as_prompt_block() for s in query_source_snippets(query, n_results, collection_name)]
