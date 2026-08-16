"""Centralized, typed application configuration.

Single source of truth for environment configuration, built on
``pydantic-settings``. Replaces scattered ``os.getenv()`` calls with one typed,
validated, self-documenting surface.

Precedence: process environment first, then ``Backend/.env``. Every default
here MUST match the historical ``os.getenv`` fallback so migrating a consumer is
behaviour-preserving.

Consumers are migrated incrementally. ``utils/llm.py`` is the first; until a
module is migrated it keeps its own ``os.getenv`` default, which is identical to
the value declared here (this class doubles as the documented config surface).

Usage:
    from config import get_settings
    settings = get_settings()          # cached singleton
    model = settings.sentinel_llm_model
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# .env sits next to this file (Backend/.env); resolve absolutely so config is
# CWD-independent (works from `python main.py`, the shim, pytest, or a container).
_ENV_FILE = str(Path(__file__).resolve().parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # tolerate the many env vars not yet modelled here
    )

    # ── LLM / Vertex AI ───────────────────────────────── (utils/llm.py: MIGRATED)
    llm_provider: str = ""                       # LLM_PROVIDER: "gemini" → AI Studio
    sentinel_llm_model: str = "gemini-2.0-flash"  # SENTINEL_LLM_MODEL
    gemini_api_key: str = ""                     # GEMINI_API_KEY (AI Studio path)
    vertex_ai_project_id: str = ""               # VERTEX_AI_PROJECT_ID (fail-fast if empty on Vertex path)
    vertex_ai_location: str = "us-central1"      # VERTEX_AI_LOCATION

    # ── RAG / vector store ───────────────────── (database/*: not yet migrated)
    sentinel_rag_mode: str = "standard"          # SENTINEL_RAG_MODE: naive|standard|full
    chroma_collection_name: str = "code_sources"  # CHROMA_COLLECTION_NAME
    sentinel_chroma_dir: str = "./chroma_data"   # SENTINEL_CHROMA_DIR (fallback under CHROMA_PERSIST_DIR)
    chroma_persist_dir: Optional[str] = None     # CHROMA_PERSIST_DIR (overrides sentinel_chroma_dir)
    sentinel_embedding_model: str = "jinaai/jina-embeddings-v2-base-code"  # SENTINEL_EMBEDDING_MODEL
    sentinel_embed_max_seq: int = 2048           # SENTINEL_EMBED_MAX_SEQ
    sentinel_embed_batch_size: int = 8           # SENTINEL_EMBED_BATCH_SIZE
    sentinel_reranker_enabled: bool = False      # SENTINEL_RERANKER_ENABLED
    sentinel_reranker_overfetch: int = 3         # SENTINEL_RERANKER_OVERFETCH
    sentinel_reranker_model: str = "jinaai/jina-reranker-v2-base-multilingual"  # SENTINEL_RERANKER_MODEL

    # ── Pipeline / execution ─────────────────── (agents/*, main.py: not yet migrated)
    sentinel_base_url: str = "http://localhost:8000"     # SENTINEL_BASE_URL (target app)
    sentinel_max_heal: Optional[int] = None      # SENTINEL_MAX_HEAL (None → ProjectState default 2)
    sentinel_sast: bool = True                   # SENTINEL_SAST
    sentinel_executor_run_pytest: bool = True    # SENTINEL_EXECUTOR_RUN_PYTEST
    sentinel_repeat_cap: Optional[int] = None    # SENTINEL_REPEAT_CAP (executor; None → 2000)
    sentinel_pytest_repeat_cap: int = 200        # SENTINEL_PYTEST_REPEAT_CAP (compiler)
    sentinel_pytest_timeout_sec: int = 900       # SENTINEL_PYTEST_TIMEOUT_SEC
    sentinel_compiler_max_tests_per_file: int = 80   # SENTINEL_COMPILER_MAX_TESTS_PER_FILE
    sentinel_compiler_max_adversarial: int = 200     # SENTINEL_COMPILER_MAX_ADVERSARIAL
    sentinel_repo_root: Optional[str] = None     # SENTINEL_REPO_ROOT (surface resolver)
    sentinel_workspace_root: Optional[str] = None    # SENTINEL_WORKSPACE_ROOT (compiler output)

    # ── API shim ─────────────────────────────── (shim/*: not yet migrated)
    sentinel_shim_max_concurrent_runs: int = 2   # SENTINEL_SHIM_MAX_CONCURRENT_RUNS

    # ── Observability ─────────────────────────── (consumed by the logging step)
    sentinel_log_level: str = "INFO"             # SENTINEL_LOG_LEVEL


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings singleton. Call this everywhere; never build a
    fresh ``Settings()`` per use. Tests that need to override env may call
    ``get_settings.cache_clear()`` after monkeypatching."""
    return Settings()
