"""AST chunker — tree-sitter 0.23/0.25 API compatibility."""

from __future__ import annotations

import pytest

from database.ast_chunker import (
    AstChunkerUnavailable,
    ast_chunk_source,
    ast_chunk_supported,
)


def test_ast_chunk_supported_languages():
    assert ast_chunk_supported("python")
    assert ast_chunk_supported("jsx")
    assert not ast_chunk_supported("dockerfile")


def test_ast_chunk_python_boundaries():
    source = (
        "import os\n"
        "\n"
        "def foo():\n"
        "    return 1\n"
        "\n"
        "class Bar:\n"
        "    pass\n"
    )
    chunks = list(ast_chunk_source(source, "python"))
    assert len(chunks) >= 2
    texts = [text for _start, _end, text in chunks]
    assert any("def foo" in t for t in texts)
    assert any("class Bar" in t for t in texts)
    # Imports should ride with the first declaration, not stand alone.
    assert any("import os" in t for t in texts)


def test_ast_chunk_unsupported_raises():
    with pytest.raises(AstChunkerUnavailable):
        list(ast_chunk_source("x = 1", "dockerfile"))
