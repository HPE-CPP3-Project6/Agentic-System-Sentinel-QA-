"""LLM client factory — Gemini 2.5 Flash.

Note: using a hosted model (Gemini) means prompts, requirement text, and any
retrieved source-code context leave the local environment. This is a
deliberate departure from the original data-sovereignty brief; revisit if
HPE re-imposes air-gapped execution.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()


def get_local_llm(
    temperature: float = 0.1,
    model: str | None = None,
    json_mode: bool = False,
) -> ChatGoogleGenerativeAI:
    """Return a ChatGoogleGenerativeAI instance configured for Gemini 2.5 Flash.

    Args:
        temperature: sampling temperature.
        model: override the model id (defaults to SENTINEL_LLM_MODEL or
            "gemini-2.5-flash").
        json_mode: if True, force Gemini to emit `application/json` so every
            response is parseable without regex scraping. Every agent that
            returns structured output should set this.
    """
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is not set — required for Gemini 2.5 Flash."
        )

    kwargs = {
        "model": model or os.getenv("SENTINEL_LLM_MODEL", "gemini-2.5-flash"),
        "temperature": temperature,
        "google_api_key": api_key,
    }
    if json_mode:
        # Gemini structured-output switch. Pass as a direct kwarg — recent
        # langchain-google-genai versions warn if it's nested under model_kwargs.
        kwargs["response_mime_type"] = "application/json"

    return ChatGoogleGenerativeAI(**kwargs)
