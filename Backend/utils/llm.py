"""LLM client factory — Gemini 2.5 Flash.

Note: using a hosted model (Gemini) means prompts, requirement text, and any
retrieved source-code context leave the local environment. This is a
deliberate departure from the original data-sovereignty brief; revisit if
HPE re-imposes air-gapped execution.
"""

from __future__ import annotations

import os
from langchain_google_genai import ChatGoogleGenerativeAI


def get_local_llm(temperature: float = 0.1, model: str | None = None) -> ChatGoogleGenerativeAI:
    """Return a ChatGoogleGenerativeAI instance configured for Gemini 2.5 Flash.

    The function name is kept for backward compatibility with existing agents;
    despite the name, the model is hosted by Google.
    """
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is not set — required for Gemini 2.5 Flash."
        )
    return ChatGoogleGenerativeAI(
        model=model or os.getenv("SENTINEL_LLM_MODEL", "gemini-2.5-flash"),
        temperature=temperature,
        google_api_key=api_key,
    )
