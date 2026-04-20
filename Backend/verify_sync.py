#!/usr/bin/env python3
"""Verify Sovereign Sync Service: Check what's in Chroma DB."""

from __future__ import annotations

import os
from pathlib import Path
from collections import defaultdict

import chromadb

# Configuration
CHROMA_PERSIST_DIR = Path(os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"))
COLLECTION_NAME = "code_sources"


def verify_sync():
    """Query and display Chroma DB statistics."""
    print("\n" + "=" * 70)
    print("SOVEREIGN SYNC SERVICE — VERIFICATION REPORT")
    print("=" * 70 + "\n")

    # Connect to Chroma
    try:
        client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        collection = client.get_or_create_collection(name=COLLECTION_NAME)
        print(f"✓ Connected to Chroma DB at: {CHROMA_PERSIST_DIR}")
    except Exception as e:
        print(f"✗ Failed to connect to Chroma DB: {e}")
        return

    # Get collection stats
    try:
        count = collection.count()
        print(f"✓ Total chunks indexed: {count}\n")

        if count == 0:
            print("⚠ No chunks found. Sync may not have completed yet.")
            print("   Try running: python database/github_sync.py --repo <URL>\n")
            return

    except Exception as e:
        print(f"✗ Failed to get collection count: {e}\n")
        return

    # Fetch and analyze all documents
    try:
        all_docs = collection.get(include=["metadatas", "documents"])
        ids = all_docs.get("ids", [])
        metadatas = all_docs.get("metadatas", [])
        documents = all_docs.get("documents", [])

        # Group by file path
        files_info = defaultdict(lambda: {"chunks": 0, "languages": set(), "size": 0})

        for idx, (doc_id, metadata, doc_text) in enumerate(
            zip(ids, metadatas, documents)
        ):
            file_path = metadata.get("file_path", "unknown")
            language = metadata.get("language", "text")
            file_size = metadata.get("file_size", 0)
            chunk_index = metadata.get("chunk_index", 0)

            files_info[file_path]["chunks"] += 1
            files_info[file_path]["languages"].add(language)
            files_info[file_path]["size"] = file_size

        # Display file statistics
        print("📊 FILES INDEXED:")
        print("-" * 70)
        for file_path in sorted(files_info.keys()):
            info = files_info[file_path]
            languages = ", ".join(sorted(info["languages"]))
            file_size_kb = info["size"] / 1024
            chunks = info["chunks"]
            print(
                f"  {file_path:45} | {chunks:3} chunks | "
                f"{file_size_kb:6.1f} KB | {languages}"
            )

        print("-" * 70)
        print(f"  Total unique files: {len(files_info)}\n")

        # Language breakdown
        print("🔤 LANGUAGE BREAKDOWN:")
        print("-" * 70)
        lang_stats = defaultdict(int)
        for file_path, info in files_info.items():
            for lang in info["languages"]:
                lang_stats[lang] += info["chunks"]

        for lang in sorted(lang_stats.keys()):
            print(f"  {lang:10} : {lang_stats[lang]:5} chunks")

        print("-" * 70 + "\n")

        # Show sample chunks
        print("📄 SAMPLE CHUNKS (first 3):")
        print("-" * 70)
        for i, (doc_id, metadata, doc_text) in enumerate(zip(ids[:3], metadatas[:3], documents[:3])):
            file_path = metadata.get("file_path", "unknown")
            chunk_idx = metadata.get("chunk_index", 0)
            chunk_count = metadata.get("chunk_count", 0)
            synced_at = metadata.get("synced_at", "unknown")

            print(f"\n[Chunk {i + 1}]")
            print(f"  File: {file_path}")
            print(f"  Chunk: {chunk_idx + 1}/{chunk_count}")
            print(f"  Synced: {synced_at}")
            print(f"  Preview: {doc_text[:150]}...")

        print("\n" + "-" * 70)
        print("\n✅ SYNC VERIFICATION COMPLETE")
        print(f"   Status: Chroma DB contains {count} indexed code chunks")
        print(f"   Files:  {len(files_info)} source files tracked\n")

    except Exception as e:
        print(f"✗ Failed to analyze documents: {e}\n")


if __name__ == "__main__":
    verify_sync()
