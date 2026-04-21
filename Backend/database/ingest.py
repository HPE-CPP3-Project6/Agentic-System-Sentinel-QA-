"""CLI: index a source tree into the ChromaDB `code_sources` collection.

Usage:
    python -m database.ingest <path-to-source-root> [--reset]
"""

from __future__ import annotations

import argparse
import sys

from .vector_store import ingest_source_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest source tree into Chroma.")
    parser.add_argument("root", help="Path to the source repository root.")
    parser.add_argument("--reset", action="store_true", help="Drop existing collection first.")
    parser.add_argument("--collection", default="code_sources")
    args = parser.parse_args(argv)

    summary = ingest_source_tree(args.root, collection_name=args.collection, reset=args.reset)
    print(
        f"Indexed {summary['files_indexed']} files → "
        f"{summary['chunks_written']} chunks in '{args.collection}'."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
