#!/usr/bin/env python3
"""Sovereign Sync Service: Automatic Chroma DB sync from GitHub repositories.

Monitors a remote GitHub repo, detects code changes via git diff, and
automatically upserts/deletes vectors in the local Chroma persistent store.

Runs as a continuous daemon (5-minute sync intervals).
"""

from __future__ import annotations

import os
import sys
import time
import logging
import subprocess
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Set
from datetime import datetime

import chromadb
from git import Repo, GitCommandError
from langchain_community.document_loaders import DirectoryLoader
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SYNC] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sync.log"),
    ],
)
logger = logging.getLogger(__name__)

# Configuration
GITHUB_REPO_URL = os.getenv(
    "GITHUB_REPO_URL",
    "https://github.com/example/sentinel-qa-app.git"
)
REPO_CACHE_DIR = Path(os.getenv("REPO_CACHE_DIR", "./repo_cache"))
CHROMA_PERSIST_DIR = Path(os.getenv("CHROMA_PERSIST_DIR", "./chroma_data"))
SYNC_INTERVAL_SECONDS = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))  # 5 minutes

# File extensions to track
TRACKED_EXTENSIONS = {".py", ".tsx", ".jsx", ".ts"}

# Chroma collection name
COLLECTION_NAME = "code_sources"

# Chunk size for code splitting
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128


class SovereignSyncService:
    """Manages syncing GitHub repository code into Chroma DB."""

    def __init__(
        self,
        repo_url: str,
        cache_dir: Path,
        chroma_dir: Path,
        sync_interval: int = 300,
    ):
        """Initialize the sync service.

        Args:
            repo_url: GitHub repository URL
            cache_dir: Local directory to cache the repo
            chroma_dir: Chroma persistent directory
            sync_interval: Seconds between sync cycles
        """
        self.repo_url = repo_url
        self.cache_dir = cache_dir
        self.chroma_dir = chroma_dir
        self.sync_interval = sync_interval
        self.repo: Optional[Repo] = None
        self.client: Optional[chromadb.PersistentClient] = None
        self.collection = None
        self.previous_commit: Optional[str] = None

        self._initialize()

    def _initialize(self) -> None:
        """Initialize Chroma client and prepare repository."""
        logger.info(f"Initializing Sovereign Sync Service")
        logger.info(f"  Repo URL: {self.repo_url}")
        logger.info(f"  Cache Dir: {self.cache_dir}")
        logger.info(f"  Chroma Dir: {self.chroma_dir}")

        # Initialize Chroma client
        self.client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"Chroma collection '{COLLECTION_NAME}' ready")

        # Initialize or update repository
        self._setup_repository()

    def _setup_repository(self) -> None:
        """Clone or open existing repository."""
        if self.cache_dir.exists() and (self.cache_dir / ".git").exists():
            logger.info(f"Repository exists at {self.cache_dir}. Opening...")
            self.repo = Repo(str(self.cache_dir))
            self.previous_commit = self.repo.head.commit.hexsha
        else:
            logger.info(f"Cloning repository from {self.repo_url}...")
            self.cache_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.repo = Repo.clone_from(self.repo_url, str(self.cache_dir))
                self.previous_commit = self.repo.head.commit.hexsha
                logger.info(f"Repository cloned successfully")
            except GitCommandError as e:
                logger.error(f"Failed to clone repository: {e}")
                raise

    def _pull_latest_changes(self) -> bool:
        """Pull latest changes from remote.

        Returns:
            True if new commits were fetched, False otherwise.
        """
        try:
            current_sha = self.repo.head.commit.hexsha
            origin = self.repo.remote("origin")
            origin.pull()
            new_sha = self.repo.head.commit.hexsha

            if current_sha == new_sha:
                logger.info("No new commits found")
                return False

            logger.info(f"Pulled new changes ({current_sha[:8]} -> {new_sha[:8]})")
            return True
        except GitCommandError as e:
            logger.error(f"Failed to pull latest changes: {e}")
            return False

    def _get_changed_files(self) -> Dict[str, Set[str]]:
        """Detect changed files using git diff.

        Returns:
            Dict with keys 'added', 'modified', 'deleted' containing file paths.
        """
        try:
            # Get diff between previous and current HEAD
            if self.previous_commit is None:
                # First sync: treat all files as added
                diff_index = self.repo.head.commit.parents[0].diff(self.repo.head.commit) if self.repo.head.commit.parents else self.repo.index.diff(None)
                changed = {
                    "added": set(),
                    "modified": set(),
                    "deleted": set(),
                }
            else:
                # Subsequent syncs: use git diff
                diff_index = self.repo.commit(self.previous_commit).diff(
                    self.repo.head.commit
                )
                changed = {
                    "added": set(),
                    "modified": set(),
                    "deleted": set(),
                }

            # Categorize changes
            for item in diff_index:
                # Get the file path (use new_path if available, otherwise old_path)
                file_path = item.b_path or item.a_path

                # Filter by extension
                if not any(file_path.endswith(ext) for ext in TRACKED_EXTENSIONS):
                    continue

                if item.change_type == "A":  # Added
                    changed["added"].add(file_path)
                elif item.change_type == "M":  # Modified
                    changed["modified"].add(file_path)
                elif item.change_type == "D":  # Deleted
                    changed["deleted"].add(item.a_path)

            self.previous_commit = self.repo.head.commit.hexsha
            return changed

        except Exception as e:
            logger.error(f"Failed to get changed files: {e}")
            return {"added": set(), "modified": set(), "deleted": set()}

    def _parse_and_chunk_file(self, file_path: str) -> List[Dict]:
        """Parse and chunk a source file into documents.

        Args:
            file_path: Relative path to file in repository

        Returns:
            List of document chunks with metadata
        """
        full_path = self.cache_dir / file_path

        if not full_path.exists():
            logger.warning(f"File does not exist: {file_path}")
            return []

        try:
            # Determine language based on extension
            ext = full_path.suffix
            if ext == ".py":
                language = Language.PYTHON
            elif ext in {".tsx", ".jsx"}:
                language = Language.TYPESCRIPT
            elif ext == ".ts":
                language = Language.TYPESCRIPT
            else:
                language = None

            # Read file content
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Create splitter
            if language:
                splitter = RecursiveCharacterTextSplitter.from_language(
                    language=language,
                    chunk_size=CHUNK_SIZE,
                    chunk_overlap=CHUNK_OVERLAP,
                )
            else:
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=CHUNK_SIZE,
                    chunk_overlap=CHUNK_OVERLAP,
                )

            # Split content
            chunks = splitter.split_text(content)

            # Create documents with metadata
            documents = []
            for idx, chunk in enumerate(chunks):
                doc = {
                    "id": f"{file_path}#{idx}",
                    "content": chunk,
                    "metadata": {
                        "file_path": file_path,
                        "chunk_index": idx,
                        "language": language.value if language else "text",
                        "file_size": len(content),
                        "chunk_count": len(chunks),
                        "synced_at": datetime.now().isoformat(),
                    },
                }
                documents.append(doc)

            logger.debug(f"Chunked {file_path} into {len(chunks)} pieces")
            return documents

        except Exception as e:
            logger.error(f"Failed to parse file {file_path}: {e}")
            return []

    def _upsert_files(self, file_paths: Set[str]) -> int:
        """Upsert files into Chroma DB.

        Args:
            file_paths: Set of file paths to upsert

        Returns:
            Number of chunks upserted
        """
        if not file_paths:
            return 0

        total_chunks = 0
        for file_path in sorted(file_paths):
            documents = self._parse_and_chunk_file(file_path)

            if not documents:
                continue

            # Prepare data for Chroma upsert
            ids = [doc["id"] for doc in documents]
            documents_text = [doc["content"] for doc in documents]
            metadatas = [doc["metadata"] for doc in documents]

            try:
                self.collection.upsert(
                    ids=ids,
                    documents=documents_text,
                    metadatas=metadatas,
                )
                total_chunks += len(documents)
                logger.info(f"  Upserted {file_path} ({len(documents)} chunks)")
            except Exception as e:
                logger.error(f"  Failed to upsert {file_path}: {e}")

        return total_chunks

    def _delete_files(self, file_paths: Set[str]) -> int:
        """Delete files from Chroma DB.

        Args:
            file_paths: Set of file paths to delete

        Returns:
            Number of chunks deleted
        """
        if not file_paths:
            return 0

        total_deleted = 0
        for file_path in sorted(file_paths):
            try:
                # Delete all chunks for this file using metadata filter
                self.collection.delete(
                    where={"file_path": {"$eq": file_path}}
                )
                logger.info(f"  Deleted {file_path} from Chroma")
                total_deleted += 1
            except Exception as e:
                logger.error(f"  Failed to delete {file_path}: {e}")

        return total_deleted

    def sync_cycle(self) -> None:
        """Execute a single sync cycle."""
        logger.info("=" * 70)
        logger.info("Starting sync cycle...")

        try:
            # Pull latest changes
            has_changes = self._pull_latest_changes()

            if not has_changes:
                logger.info("Sync cycle complete. No updates needed.")
                return

            # Detect changed files
            changed = self._get_changed_files()
            added = changed["added"]
            modified = changed["modified"]
            deleted = changed["deleted"]

            total_added = len(added)
            total_modified = len(modified)
            total_deleted = len(deleted)

            logger.info(
                f"Detected {total_added + total_modified + total_deleted} "
                f"changed files ({total_added} added, {total_modified} modified, "
                f"{total_deleted} deleted)"
            )

            # Process deletions
            if deleted:
                logger.info(f"Processing {len(deleted)} deleted files...")
                deleted_count = self._delete_files(deleted)
                logger.info(f"Deleted {deleted_count} files from Chroma")

            # Process additions and modifications
            to_upsert = added | modified
            if to_upsert:
                logger.info(f"Processing {len(to_upsert)} added/modified files...")
                chunks_count = self._upsert_files(to_upsert)
                logger.info(f"Upserted {chunks_count} code chunks into Chroma")

            logger.info("Sync cycle complete.")

        except Exception as e:
            logger.error(f"Sync cycle failed: {e}", exc_info=True)

    def run(self) -> None:
        """Start the continuous sync daemon."""
        logger.info(f"Sovereign Sync Service started (interval: {self.sync_interval}s)")

        try:
            while True:
                self.sync_cycle()
                logger.info(f"Waiting {self.sync_interval}s until next sync...")
                time.sleep(self.sync_interval)
        except KeyboardInterrupt:
            logger.info("Sync service interrupted by user")
        except Exception as e:
            logger.error(f"Unexpected error in sync service: {e}", exc_info=True)
        finally:
            logger.info("Sovereign Sync Service stopped")


def main():
    """Entry point for the sync service."""
    parser = argparse.ArgumentParser(
        description="Sovereign Sync Service: Auto-sync GitHub repo to Chroma DB"
    )
    parser.add_argument(
        "--repo",
        default=GITHUB_REPO_URL,
        help="GitHub repository URL (default from GITHUB_REPO_URL env var)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=REPO_CACHE_DIR,
        help="Local repository cache directory (default from REPO_CACHE_DIR env var)",
    )
    parser.add_argument(
        "--chroma-dir",
        type=Path,
        default=CHROMA_PERSIST_DIR,
        help="Chroma persistence directory (default from CHROMA_PERSIST_DIR env var)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=SYNC_INTERVAL_SECONDS,
        help="Sync interval in seconds (default from SYNC_INTERVAL_SECONDS env var)",
    )

    args = parser.parse_args()

    service = SovereignSyncService(
        repo_url=args.repo,
        cache_dir=args.cache_dir,
        chroma_dir=args.chroma_dir,
        sync_interval=args.interval,
    )
    service.run()


if __name__ == "__main__":
    main()
