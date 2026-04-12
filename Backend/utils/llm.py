"""Local LLM client factory — keeps data sovereignty by defaulting to an air-gapped endpoint."""

from __future__ import annotations

import os
from langchain_ollama import ChatOllama


def get_local_llm(temperature: float = 0.1, model: str | None = None) -> ChatOllama:
    """Return a ChatOllama instance pointing at the locally-hosted model.

    Why: HPE requires data sovereignty — no requirement text, source code, or payloads
    may leave the local environment. All agents must share this single factory.
    """
    return ChatOllama(
        model=model or os.getenv("SENTINEL_LLM_MODEL", "llama3.1:8b-instruct"),
        base_url=os.getenv("SENTINEL_LLM_BASE_URL", "http://localhost:11434"),
        temperature=temperature,
    )
