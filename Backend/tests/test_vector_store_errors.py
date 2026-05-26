"""Golden tests for vector_store retrieval error logging (C5 fix).

Behavior pinned: when retrieval cannot reach Chroma — embedding OOM, missing
collection, query crash, empty index — the path must:
    1. Return [] (never raise; downstream sees an empty retrieval and emits
       coverage_gaps, which is graceful degradation)
    2. Emit a logger.warning that explains WHY (exception type + truncated
       message + context like collection name)

Before C5 the second part was missing — empty retrievals were
indistinguishable from "Chroma is fine but the query genuinely matched
nothing", which made triage genuinely painful.

Run from Backend/:
    pytest tests/test_vector_store_errors.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from database import vector_store as vs


# --------------------------------------------------------------------------- #
# Path 1: get_collection raises ValueError (embedding-fn mismatch)             #
#         → first except catches; we fall back to no-embedding-fn open.       #
#         If THAT also fails, we log + return [].                              #
# --------------------------------------------------------------------------- #


def test_embedding_mismatch_fallback_failure_logs_and_returns_empty(caplog):
    client = MagicMock()
    # Both .get_collection calls raise — the embedding-mismatch one raises
    # ValueError, the fallback raises a generic Exception.
    client.get_collection.side_effect = [
        ValueError("embedding function dim mismatch"),
        RuntimeError("collection table missing"),
    ]

    with patch.object(vs, "get_chroma_client", return_value=client), \
         patch.object(vs, "_get_embedding_function", return_value=MagicMock()):
        with caplog.at_level("WARNING", logger=vs.logger.name):
            result = vs.query_source_snippets("anything", n_results=3)

    assert result == []
    # First warning is the embedding-mismatch fallback notice;
    # second is the C5-required "unavailable after fallback" message.
    messages = " ".join(r.message for r in caplog.records)
    assert "embedding config mismatch" in messages.lower() or "embedding function dim mismatch" in messages
    assert "unavailable after embedding-mismatch fallback" in messages
    assert "RuntimeError" in messages


# --------------------------------------------------------------------------- #
# Path 2: get_collection raises a generic Exception (Chroma file lock, etc.)  #
# --------------------------------------------------------------------------- #


def test_cannot_open_collection_logs_and_returns_empty(caplog):
    client = MagicMock()
    client.get_collection.side_effect = RuntimeError("chroma file locked by another process")

    with patch.object(vs, "get_chroma_client", return_value=client), \
         patch.object(vs, "_get_embedding_function", return_value=MagicMock()):
        with caplog.at_level("WARNING", logger=vs.logger.name):
            result = vs.query_source_snippets("anything", n_results=3)

    assert result == []
    messages = " ".join(r.message for r in caplog.records)
    assert "Cannot open collection" in messages
    assert "RuntimeError" in messages
    assert "chroma file locked" in messages
    # Triage hints: must mention what to check
    assert "coverage gap" in messages.lower()


# --------------------------------------------------------------------------- #
# Path 3: collection opens fine but is empty                                   #
# --------------------------------------------------------------------------- #


def test_empty_collection_logs_actionable_hint(caplog):
    collection = MagicMock()
    collection.count.return_value = 0
    client = MagicMock()
    client.get_collection.return_value = collection

    with patch.object(vs, "get_chroma_client", return_value=client), \
         patch.object(vs, "_get_embedding_function", return_value=MagicMock()):
        with caplog.at_level("WARNING", logger=vs.logger.name):
            result = vs.query_source_snippets("anything", n_results=3)

    assert result == []
    messages = " ".join(r.message for r in caplog.records)
    assert "EMPTY" in messages
    # Must tell the dev the exact next step
    assert "database.ingest" in messages


# --------------------------------------------------------------------------- #
# Path 4: collection.query raises (embedding OOM, malformed input, etc.)      #
# --------------------------------------------------------------------------- #


def test_query_failure_logs_with_context_and_returns_empty(caplog):
    collection = MagicMock()
    collection.count.return_value = 100  # non-empty so we reach .query
    collection.query.side_effect = MemoryError("torch out of memory")
    client = MagicMock()
    client.get_collection.return_value = collection

    with patch.object(vs, "get_chroma_client", return_value=client), \
         patch.object(vs, "_get_embedding_function", return_value=MagicMock()):
        with caplog.at_level("WARNING", logger=vs.logger.name):
            result = vs.query_source_snippets("a very long query string", n_results=5)

    assert result == []
    messages = " ".join(r.message for r in caplog.records)
    assert "Query against" in messages
    assert "MemoryError" in messages
    assert "torch out of memory" in messages
    # Should report context (query length, fetch_n) to aid diagnosis
    assert "chars" in messages
    assert "fetch_n" in messages
