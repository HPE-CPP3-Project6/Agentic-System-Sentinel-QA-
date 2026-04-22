"""Centralized import-time bootstrap for cache directories.

Every entry point that touches chromadb / sentence-transformers / ONNX
runtime needs these environment variables set BEFORE those packages are
imported for the first time, otherwise each will create its own cache in
an arbitrary user-home location and re-download embedding model weights.

Historically this block was copy-pasted at the top of four different
modules. It now lives here. Call `configure_caches()` once (it is
idempotent) before importing chromadb or sentence_transformers.

Example:
    from bootstrap import configure_caches
    configure_caches()
    import chromadb  # noqa: E402
"""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent
_DEFAULT_CACHE_DIR = _BACKEND_ROOT / "chroma_models_cache"

_CONFIGURED = False


def configure_caches(cache_dir: str | os.PathLike[str] | None = None) -> str:
    """Point chromadb / HuggingFace / ONNX caches at a project-local directory.

    Sets the four environment variables exactly once per process. Subsequent
    calls are no-ops so later imports cannot silently re-point the cache.

    Returns the absolute cache directory path.
    """
    global _CONFIGURED

    resolved = Path(cache_dir).resolve() if cache_dir else _DEFAULT_CACHE_DIR
    resolved.mkdir(parents=True, exist_ok=True)
    resolved_str = str(resolved)

    if _CONFIGURED:
        return resolved_str

    os.environ.setdefault("CHROMA_HOME", resolved_str)
    os.environ.setdefault("HF_HOME", resolved_str)
    os.environ.setdefault("ONNXRUNTIME_CACHE_DIR", resolved_str)
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", resolved_str)

    _CONFIGURED = True
    return resolved_str


CACHE_DIR = configure_caches()
