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

from bootstrap import configure_caches

_CHROMA_HOME = configure_caches()

import chromadb  # noqa: E402
from chromadb.config import Settings  # noqa: E402
from git import Repo, GitCommandError  # noqa: E402

from database.vector_store import (  # noqa: E402
    EMBEDDING_MODEL,
    JinaCodeEmbeddingFunction,
)

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

# File-type gating — what gets indexed into Chroma.
# The broader set grounds Rule 1 protocol/deployment assertions (vite.config,
# nginx.conf, FastAPI middleware, .env.example) that application source
# code alone cannot back.

TRACKED_SUFFIXES: Set[str] = {
    # Source code
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".vue",
    # Markup / templates
    ".html",
    # Config & deployment
    ".json", ".yml", ".yaml", ".toml",
    ".conf", ".cfg", ".ini",
    # Database / migrations
    ".sql",
    # Env schemas (shape only — real .env is in SKIP_BASENAMES)
    ".env.example", ".env.sample", ".env.template",
}

TRACKED_BASENAMES: Set[str] = {
    "Dockerfile", "dockerfile",
    "Makefile", "makefile",
    "Caddyfile", "caddyfile",
    "nginx.conf",
}

SKIP_BASENAMES: Set[str] = {
    # Real env files with secrets — never index
    ".env", ".env.local", ".env.production", ".env.development", ".env.prod",
    # Lockfiles — bulk noise, zero API-contract signal
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock",
}

# Chroma collection name
COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "code_sources")


def _is_tracked(file_path: str) -> bool:
    """Return True if `file_path` should be indexed into Chroma."""
    basename = os.path.basename(file_path)
    if basename in SKIP_BASENAMES:
        return False
    if basename in TRACKED_BASENAMES:
        return True
    return any(basename.endswith(suffix) for suffix in TRACKED_SUFFIXES)


def _lang_label(file_path: str) -> str:
    """Human-readable language label stored in Chroma metadata."""
    name = os.path.basename(file_path).lower()
    # Specific basenames first so nginx.conf -> "nginx", not "config".
    if name == "dockerfile":
        return "dockerfile"
    if name == "makefile":
        return "makefile"
    if name == "caddyfile":
        return "caddy"
    if name == "nginx.conf":
        return "nginx"
    if name.endswith((".env.example", ".env.sample", ".env.template")):
        return "env"
    ext = os.path.splitext(name)[1]
    simple = {
        ".py": "python", ".ts": "typescript", ".tsx": "tsx",
        ".js": "javascript", ".jsx": "jsx",
        ".mjs": "javascript", ".cjs": "javascript",
        ".vue": "vue", ".html": "html",
        ".json": "json", ".yml": "yaml", ".yaml": "yaml",
        ".toml": "toml", ".conf": "config", ".cfg": "config", ".ini": "config",
        ".sql": "sql",
    }
    return simple.get(ext, "text")


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

        # Keep all model artifacts inside the project workspace cache.
        os.environ["SENTENCE_TRANSFORMERS_HOME"] = _CHROMA_HOME
        os.environ["HF_HOME"] = _CHROMA_HOME

        # Explicitly load the embedding function (code-native, 768-dim).
        emb_fn = JinaCodeEmbeddingFunction()

        # Initialize Chroma client.
        settings = Settings(
            chroma_home=_CHROMA_HOME,
            anonymized_telemetry=False,
            is_persistent=True
        )
        self.client = chromadb.PersistentClient(path=str(self.chroma_dir), settings=settings)

        # Pass the embedding function to the collection.
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=emb_fn,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"Chroma collection '{COLLECTION_NAME}' ready")

        # Initialize or update repository
        self._setup_repository()

    @property
    def _sha_state_file(self) -> Path:
        """Sidecar file persisting the last synced SHA across daemon restarts.

        Without this, a restart resets `previous_commit` to None and the next
        sync re-embeds the ENTIRE corpus (every file flagged as 'added'). On a
        5k-file repo that is 30+ minutes of Jina embedding per restart.
        """
        return self.cache_dir.parent / f".{self.cache_dir.name}_last_sync_sha"

    def _load_last_synced_sha(self) -> Optional[str]:
        try:
            sha = self._sha_state_file.read_text(encoding="utf-8").strip()
            return sha or None
        except (OSError, UnicodeDecodeError):
            return None

    def _persist_last_synced_sha(self, sha: str) -> None:
        try:
            self._sha_state_file.write_text(sha, encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "Could not persist last-synced SHA to %s (%s) — next restart "
                "will re-index everything.",
                self._sha_state_file,
                exc,
            )

    def _setup_repository(self) -> None:
        """Clone or open existing repository, restore last-synced SHA if present."""
        if self.cache_dir.exists() and (self.cache_dir / ".git").exists():
            logger.info(f"Repository exists at {self.cache_dir}. Opening...")
            self.repo = Repo(str(self.cache_dir))
        else:
            logger.info(f"Cloning repository from {self.repo_url}...")
            self.cache_dir.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.repo = Repo.clone_from(self.repo_url, str(self.cache_dir))
                logger.info(f"Repository cloned successfully")
            except GitCommandError as e:
                logger.error(f"Failed to clone repository: {e}")
                raise

        # Restore the SHA we synced to last time. If absent (cold start, or
        # broken sidecar), fall back to None → next sync indexes everything,
        # same as before. Either way, every successful cycle persists.
        self.previous_commit = self._load_last_synced_sha()
        if self.previous_commit:
            logger.info(
                f"Resumed from last-synced commit {self.previous_commit[:8]} "
                f"(only diff vs current HEAD will be embedded)."
            )
        else:
            logger.info(
                "No prior sync state found — first cycle will index ALL "
                "tracked files."
            )

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

        Handles all five change types git emits:
            A — Added         → upsert at new path
            M — Modified      → upsert at same path
            D — Deleted       → drop vectors for that path
            R — Renamed       → drop vectors at old path + upsert at new path
            T — Type changed  → treat as modify (path unchanged; file/symlink swap)

        Previously only A/M/D were handled, so a renamed file left STALE vectors
        at the old path AND never gained vectors at the new path. Real bug —
        renames are common in any active repo.

        Returns:
            Dict with keys 'added', 'modified', 'deleted' containing file paths.
        """
        try:
            changed = {
                "added": set(),
                "modified": set(),
                "deleted": set(),
            }

            # First sync: get all files from HEAD
            if self.previous_commit is None:
                for item in self.repo.index.entries.keys():
                    file_path = item[0]
                    if _is_tracked(file_path):
                        changed["added"].add(file_path)
            else:
                # Subsequent syncs: use git diff
                diff_index = self.repo.commit(self.previous_commit).diff(
                    self.repo.head.commit
                )

                for item in diff_index:
                    new_path = item.b_path
                    old_path = item.a_path
                    primary = new_path or old_path

                    if item.change_type == "A":
                        if _is_tracked(primary):
                            changed["added"].add(primary)
                    elif item.change_type == "M":
                        if _is_tracked(primary):
                            changed["modified"].add(primary)
                    elif item.change_type == "D":
                        # _is_tracked check uses the old path — that's the one
                        # whose vectors actually live in Chroma.
                        if _is_tracked(old_path):
                            changed["deleted"].add(old_path)
                    elif item.change_type == "R":
                        # Rename: drop old vectors (if tracked), add at new
                        # path (if tracked). Possible the new file type is
                        # not tracked anymore (e.g. .py → .md) — that's still
                        # a delete-old, no add-new.
                        if old_path and _is_tracked(old_path):
                            changed["deleted"].add(old_path)
                        if new_path and _is_tracked(new_path):
                            changed["added"].add(new_path)
                    elif item.change_type == "T":
                        # Type change (regular file <-> symlink, etc.) at the
                        # same path. Safest treatment: re-embed.
                        if _is_tracked(primary):
                            changed["modified"].add(primary)
                    else:
                        logger.debug(
                            "Unhandled git diff change_type=%r for %s; "
                            "treating as modify.",
                            item.change_type, primary,
                        )
                        if _is_tracked(primary):
                            changed["modified"].add(primary)

            # Advance our cursor — but DON'T persist until the cycle's upserts
            # actually succeed (see sync_cycle), so a crash mid-cycle doesn't
            # leave Chroma half-updated AND the sidecar advanced past the gap.
            self.previous_commit = self.repo.head.commit.hexsha
            return changed

        except Exception as e:
            logger.error(f"Failed to get changed files: {e}")
            return {"added": set(), "modified": set(), "deleted": set()}

    def _parse_and_chunk_file(self, file_path: str) -> List[Dict]:
        """Parse and chunk a source file into documents.

        Uses the unified AST-aware chunker from `database.vector_store`
        (tree-sitter for Python/JS/JSX/TS/TSX, line-based fallback
        otherwise). Both ingestion paths share this so a given source
        file produces identical vectors regardless of which path ran.
        """
        full_path = self.cache_dir / file_path

        if not full_path.exists():
            logger.warning(f"File does not exist: {file_path}")
            return []

        try:
            lang_label = _lang_label(file_path)

            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            if not content.strip():
                return []

            from database.vector_store import _chunk_source

            lines = content.splitlines(keepends=True)
            chunk_tuples = list(_chunk_source(content, lines, lang_label))

            documents: List[Dict] = []
            for idx, (start_line, end_line, chunk_text) in enumerate(chunk_tuples):
                # Synthetic header injected BEFORE chunk text so the embedding
                # encodes file identity and language into the dense vector.
                # This is the single largest precision win for cross-file
                # retrieval: a query like "axios baseURL" now matches the
                # axios.js chunk by file name too, not just by body tokens.
                synthetic_header = (
                    f"### FILE: {file_path} | LANG: {lang_label} ###\n\n"
                )
                enriched_content = synthetic_header + chunk_text
                documents.append(
                    {
                        "id": f"{file_path}#{idx}",
                        "content": enriched_content,
                        "metadata": {
                            "path": file_path,
                            "file_path": file_path,
                            "chunk_index": idx,
                            "start_line": start_line,
                            "end_line": end_line,
                            "language": lang_label,
                            "file_size": len(content),
                            "chunk_count": len(chunk_tuples),
                            "synced_at": datetime.now().isoformat(),
                        },
                    }
                )

            logger.debug(f"Chunked {file_path} into {len(chunk_tuples)} pieces")
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
            # Check if this is the first sync (no previous commit)
            is_first_sync = self.previous_commit is None
            
            # Pull latest changes
            has_changes = self._pull_latest_changes()

            # Force sync on first run even if no new commits
            if not has_changes and not is_first_sync:
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

            if total_added + total_modified + total_deleted == 0:
                logger.info("Sync cycle complete. No updates needed.")
                return

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

            # Persist the cursor ONLY after Chroma writes succeeded for this
            # cycle. On crash mid-cycle, sidecar stays at the prior SHA and
            # the next start replays this diff — at-least-once delivery, safe
            # because upsert is idempotent.
            self._persist_last_synced_sha(self.previous_commit)
            logger.info(
                f"Sync cycle complete. Cursor advanced to "
                f"{self.previous_commit[:8]}."
            )

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
