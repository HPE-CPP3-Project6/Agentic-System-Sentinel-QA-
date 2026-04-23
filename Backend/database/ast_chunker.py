"""AST-aware source chunker.

The previous chunking strategies sliced files by byte count (`github_sync`
used LangChain's `RecursiveCharacterTextSplitter` at 1024 chars) or by
fixed line count (`vector_store._chunk_lines` at 80 lines with overlap).
Both are syntax-blind: they routinely cut functions in half, split an
import block from the class that depends on it, and separate a decorator
from the function it decorates. The cross-encoder reranker added in
Stage 1 can re-*order* chunks but cannot un-slice a truncated function.

This module uses `tree-sitter-language-pack` to emit chunks aligned to
declaration boundaries — functions, classes, methods, type aliases,
interfaces, exports. Comments and decorators immediately preceding a
declaration stay with it. Trailing whitespace is discarded so hashes
are stable across whitespace-only edits.

Graceful fallback: if `tree-sitter-language-pack` is not installed, or
parsing fails for a given file, callers can fall back to the existing
line-based chunker via `_chunk_lines`. See `ast_chunk_source`.

Supported languages: Python, JavaScript, JSX, TypeScript, TSX.
"""

from __future__ import annotations

import logging
from typing import Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

# Map the language labels we use internally (see vector_store._LANG_BY_EXT)
# to tree-sitter-language-pack grammar ids. Unlisted languages fall back
# to the line chunker.
_LANG_GRAMMAR: dict[str, str] = {
    "python":     "python",
    "javascript": "javascript",
    "jsx":        "javascript",     # the JS grammar parses JSX fine
    "typescript": "typescript",
    "tsx":        "tsx",
}

# Per-language, the node types we treat as "natural chunk boundaries".
# Nodes not in this list are glued onto the next adjacent chunk so that
# imports, decorators, JSDoc comments, type aliases, and small top-level
# statements stay with the declaration they pertain to.
_CHUNK_NODES: dict[str, frozenset[str]] = {
    "python": frozenset({
        "function_definition",
        "decorated_definition",
        "class_definition",
        "async_function_definition",
    }),
    "javascript": frozenset({
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
        "export_statement",
        "lexical_declaration",   # top-level const foo = () => {}
    }),
    "typescript": frozenset({
        "function_declaration",
        "generator_function_declaration",
        "class_declaration",
        "method_definition",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
        "export_statement",
        "lexical_declaration",
        "abstract_class_declaration",
    }),
}
# JSX == JS grammar; TSX extends TS:
_CHUNK_NODES["jsx"] = _CHUNK_NODES["javascript"]
_CHUNK_NODES["tsx"] = _CHUNK_NODES["typescript"]


# --------------------------------------------------------------------------- #
# Parser acquisition (lazy, cached, guarded)
# --------------------------------------------------------------------------- #

_PARSER_AVAILABLE: Optional[bool] = None
_PARSER_CACHE: dict[str, object] = {}


def _tree_sitter_available() -> bool:
    """Return True iff tree-sitter-language-pack can be imported."""
    global _PARSER_AVAILABLE
    if _PARSER_AVAILABLE is not None:
        return _PARSER_AVAILABLE
    try:
        import tree_sitter_language_pack  # noqa: F401
        _PARSER_AVAILABLE = True
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "tree-sitter-language-pack unavailable (%s); AST chunker will "
            "fall back to line-based chunking.",
            exc,
        )
        _PARSER_AVAILABLE = False
    return _PARSER_AVAILABLE


def _get_parser(language: str):
    """Return a cached `tree_sitter.Parser` for `language`, or None on failure."""
    if not _tree_sitter_available():
        return None
    grammar = _LANG_GRAMMAR.get(language)
    if grammar is None:
        return None
    if grammar in _PARSER_CACHE:
        return _PARSER_CACHE[grammar]
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(grammar)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to load tree-sitter parser for %s (%s); falling back.",
            grammar,
            exc,
        )
        _PARSER_CACHE[grammar] = None
        return None
    _PARSER_CACHE[grammar] = parser
    return parser


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def ast_chunk_supported(language: str) -> bool:
    """True if we have both a grammar and chunk-node list for `language`."""
    return language in _LANG_GRAMMAR and language in _CHUNK_NODES


def ast_chunk_source(
    source: str,
    language: str,
    *,
    max_chunk_lines: int = 160,
    min_chunk_lines: int = 3,
) -> Iterator[Tuple[int, int, str]]:
    """Yield (start_line, end_line, text) tuples aligned to AST boundaries.

    Line numbers are 1-based and inclusive. `end_line` points at the last
    line containing declaration text.

    Falls back by raising `AstChunkerUnavailable` if tree-sitter or the
    requested grammar is unavailable — the caller is expected to catch
    this and invoke the line-based chunker. We raise rather than silently
    fall back so the caller can log per-file decisions.

    Chunks larger than `max_chunk_lines` are further subdivided: the
    chunker descends into the first layer of children and emits them as
    separate chunks. If even the child chunks are too big (giant React
    component body, huge Python class), it falls through to emitting the
    whole declaration as one chunk — we prefer "one big chunk that keeps
    a function whole" over "a function cut in half".

    `min_chunk_lines` merges tiny adjacent chunks (single-line exports,
    small lexical_declarations, etc.) into the next following chunk so
    we don't pollute the vector store with 1-line snippets.
    """
    if not ast_chunk_supported(language):
        raise AstChunkerUnavailable(f"no grammar for language={language!r}")

    parser = _get_parser(language)
    if parser is None:
        raise AstChunkerUnavailable(f"parser unavailable for language={language!r}")

    source_bytes = source.encode("utf-8", errors="replace")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    boundary_types = _CHUNK_NODES[language]
    lines = source.splitlines(keepends=True)
    n_lines = len(lines)
    if n_lines == 0:
        return

    # Gather the ranges of all top-level boundary nodes.
    # (start_line, end_line) are 0-indexed inclusive.
    boundaries: list[tuple[int, int, object]] = []
    for child in root.children:
        if child.type in boundary_types:
            boundaries.append((child.start_point[0], child.end_point[0], child))

    # If the file has no declarations tree-sitter recognizes as a boundary
    # (e.g. a config file that's JSON syntax pretending to be TS), fall
    # back to emitting the entire file as one chunk. Better than 1-line
    # shreds of expression statements.
    if not boundaries:
        yield (1, n_lines, "".join(lines))
        return

    # Walk boundaries, accumulating "prelude" lines (imports, comments,
    # small statements between declarations) onto the NEXT boundary so
    # context travels with the declaration that uses it.
    prelude_start = 0
    pending_merge_start: Optional[int] = None

    for idx, (b_start, b_end, node) in enumerate(boundaries):
        chunk_start = pending_merge_start if pending_merge_start is not None else prelude_start
        chunk_end = b_end

        # Only absorb prelude if it actually contains something — avoid
        # swallowing blank lines into every chunk.
        if chunk_start < b_start:
            between = "".join(lines[chunk_start:b_start])
            if not between.strip():
                chunk_start = b_start

        chunk_line_count = chunk_end - chunk_start + 1

        # Chunk too big — try to subdivide by descending one level.
        if chunk_line_count > max_chunk_lines:
            subchunks = list(_subdivide_node(node, lines, max_chunk_lines))
            if subchunks:
                # Attach any absorbed prelude to the first subchunk.
                first_s, first_e, first_t = subchunks[0]
                if chunk_start < first_s - 1:
                    prelude = "".join(lines[chunk_start:first_s - 1])
                    subchunks[0] = (chunk_start + 1, first_e, prelude + first_t)
                yield from subchunks
                prelude_start = chunk_end + 1
                pending_merge_start = None
                continue

        # Tiny chunk — merge it into the next one instead of emitting.
        if chunk_line_count < min_chunk_lines and idx + 1 < len(boundaries):
            if pending_merge_start is None:
                pending_merge_start = chunk_start
            continue

        text = "".join(lines[chunk_start:chunk_end + 1])
        yield (chunk_start + 1, chunk_end + 1, text)
        prelude_start = chunk_end + 1
        pending_merge_start = None

    # Trailing content after the last boundary (rare — module-level code
    # like `if __name__ == "__main__": main()`).
    if prelude_start < n_lines:
        trailing = "".join(lines[prelude_start:])
        if trailing.strip():
            yield (prelude_start + 1, n_lines, trailing)


def _subdivide_node(
    node,
    lines: list[str],
    max_chunk_lines: int,
) -> Iterator[Tuple[int, int, str]]:
    """Split an over-sized boundary node by descending into its children.

    Used for huge classes / components whose top-level span exceeds
    `max_chunk_lines`. Emits one chunk per child declaration; if even the
    children don't help (rare — a monolithic function body), yields the
    whole node as one chunk rather than slicing it arbitrarily.
    """
    # Find the `body` / `class_body` / `statement_block` child which
    # holds the sub-declarations. Different grammars name it differently,
    # so we just look for any named child whose own children look
    # chunkable.
    candidate_children = [c for c in node.children if c.is_named and c.child_count > 0]
    if not candidate_children:
        yield (node.start_point[0] + 1, node.end_point[0] + 1,
               "".join(lines[node.start_point[0]:node.end_point[0] + 1]))
        return

    # Pick the deepest "body"-like child.
    body = max(candidate_children, key=lambda c: c.end_point[0] - c.start_point[0])

    sub_boundaries = [
        (c.start_point[0], c.end_point[0])
        for c in body.children
        if c.is_named and (c.end_point[0] - c.start_point[0]) >= 0
    ]
    if not sub_boundaries:
        yield (node.start_point[0] + 1, node.end_point[0] + 1,
               "".join(lines[node.start_point[0]:node.end_point[0] + 1]))
        return

    # Yield the declaration header (signature + class docstring area),
    # then each child declaration.
    header_end = sub_boundaries[0][0] - 1
    if header_end >= node.start_point[0]:
        yield (
            node.start_point[0] + 1,
            header_end + 1,
            "".join(lines[node.start_point[0]:header_end + 1]),
        )

    for s, e in sub_boundaries:
        if (e - s + 1) > max_chunk_lines:
            # Still too big. Emit as-is rather than slicing arbitrarily.
            yield (s + 1, e + 1, "".join(lines[s:e + 1]))
        else:
            yield (s + 1, e + 1, "".join(lines[s:e + 1]))


class AstChunkerUnavailable(RuntimeError):
    """Raised when AST chunking cannot be performed (library missing,
    grammar unsupported, or parse failure). Caller should fall back to
    the line-based chunker."""
