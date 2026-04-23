"""Cross-encoder reranker for retrieved source snippets.

The dense bi-encoder retriever (ChromaDB + Jina code embeddings) is tuned
for RECALL: return a pool of plausibly-relevant chunks cheaply. A cross-
encoder then rescores each `(query, chunk)` pair with full bidirectional
attention — slower per call, but substantially more accurate at picking
the top-K that actually answers the query.

Integration pattern:
    1. Retriever pulls N * overfetch_ratio candidates from ChromaDB.
    2. Reranker scores each candidate against the query.
    3. Top-K after reranking are returned to the caller.

Feature-flagged so the first ingestion/query run does not silently pull
a ~600 MB model. Enable with:

    SENTINEL_RERANKER_ENABLED=1

Override the model id with:

    SENTINEL_RERANKER_MODEL=<huggingface-id>

When disabled or on any failure, `maybe_rerank_snippets` returns the
retriever's original ordering — retrieval never hard-fails on reranker
issues.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Sequence

from bootstrap import configure_caches

_CACHE_DIR = configure_caches()

logger = logging.getLogger(__name__)

DEFAULT_RERANKER_MODEL = os.getenv(
    "SENTINEL_RERANKER_MODEL",
    "jinaai/jina-reranker-v2-base-multilingual",
)

DEFAULT_OVERFETCH_RATIO = int(os.getenv("SENTINEL_RERANKER_OVERFETCH", "3"))


def is_reranker_enabled() -> bool:
    """Check the feature flag. Default OFF so cold starts do not auto-download."""
    raw = os.getenv("SENTINEL_RERANKER_ENABLED", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


class CrossEncoderReranker:
    """Lazy, process-wide singleton wrapper around a sentence-transformers CrossEncoder.

    The underlying model is loaded on first `rerank()` call and cached at
    the class level, so repeated instantiations do NOT reload weights.
    """

    _model = None  # type: ignore[var-annotated]
    _model_name: Optional[str] = None

    def __init__(self, model_name: Optional[str] = None) -> None:
        self.model_name = model_name or DEFAULT_RERANKER_MODEL

    def _load(self):
        if (
            CrossEncoderReranker._model is not None
            and CrossEncoderReranker._model_name == self.model_name
        ):
            return CrossEncoderReranker._model

        # Imported lazily so a plain `import database` does NOT pull in
        # sentence-transformers' startup cost when the reranker is disabled.
        from sentence_transformers import CrossEncoder

        logger.info("Loading cross-encoder reranker: %s", self.model_name)
        model = CrossEncoder(
            self.model_name,
            trust_remote_code=True,
            cache_folder=_CACHE_DIR,
        )
        CrossEncoderReranker._model = model
        CrossEncoderReranker._model_name = self.model_name
        return model

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_k: Optional[int] = None,
    ) -> List[int]:
        """Return document indices sorted by relevance (descending).

        Args:
            query:      text the user is trying to find.
            documents:  candidate chunk texts (order preserved on input).
            top_k:      if set, truncate to the top-K indices.

        Returns the indices into `documents`; the caller pairs them back
        with the original snippet objects to preserve path / line metadata.
        """
        if not documents:
            return []

        model = self._load()
        pairs = [[query, doc] for doc in documents]
        scores = model.predict(pairs, show_progress_bar=False)
        ranked = sorted(
            range(len(documents)),
            key=lambda i: float(scores[i]),
            reverse=True,
        )
        if top_k is not None:
            ranked = ranked[:top_k]
        return ranked


def maybe_rerank_snippets(
    query: str,
    snippets: List,
    top_k: int,
) -> List:
    """Apply cross-encoder reranking to `snippets` if the feature flag is set.

    Safe by construction: on any error (model download fails, incompatible
    weights, OOM, import failure) logs a warning and returns the retriever's
    original ordering clamped to `top_k`. Callers can unconditionally wrap
    their retrieval output in this helper.

    Args:
        query:    the retrieval query. Same string can be passed for both
                  retrieval and reranking in V1; refine per-bucket later.
        snippets: objects with a `.text` attribute (e.g. `SourceSnippet`).
        top_k:    number of snippets to return after reranking.

    Returns the top-K snippets, reranked when enabled, otherwise the first
    `top_k` in retriever order.
    """
    if not snippets:
        return []
    if not is_reranker_enabled():
        return list(snippets[:top_k]) if top_k is not None else list(snippets)

    try:
        reranker = CrossEncoderReranker()
        docs = [getattr(s, "text", str(s)) for s in snippets]
        indices = reranker.rerank(query, docs, top_k=top_k)
        return [snippets[i] for i in indices]
    except Exception as exc:  # noqa: BLE001 — reranker must never break retrieval
        logger.warning(
            "Reranker failed (%s: %s); falling back to retriever order.",
            type(exc).__name__,
            exc,
        )
        return list(snippets[:top_k]) if top_k is not None else list(snippets)
