from .reranker import (
    CrossEncoderReranker,
    is_reranker_enabled,
    maybe_rerank_snippets,
)
from .vector_store import (
    RagMode,
    RouteIntent,
    SourceSnippet,
    VerticalSliceContext,
    get_chroma_client,
    get_or_create_collection,
    ingest_source_tree,
    query_source_context,
    query_source_snippets,
    resolve_rag_mode,
)

__all__ = [
    "RagMode",
    "resolve_rag_mode",
    "RouteIntent",
    "SourceSnippet",
    "VerticalSliceContext",
    "get_chroma_client",
    "get_or_create_collection",
    "ingest_source_tree",
    "query_source_context",
    "query_source_snippets",
    # Reranker (feature-flagged)
    "CrossEncoderReranker",
    "is_reranker_enabled",
    "maybe_rerank_snippets",
]
