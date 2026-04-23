from .reranker import (
    CrossEncoderReranker,
    is_reranker_enabled,
    maybe_rerank_snippets,
)
from .vector_store import (
    RouteIntent,
    SourceSnippet,
    VerticalSliceContext,
    get_chroma_client,
    get_or_create_collection,
    ingest_source_tree,
    query_source_context,
    query_source_snippets,
)

__all__ = [
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
