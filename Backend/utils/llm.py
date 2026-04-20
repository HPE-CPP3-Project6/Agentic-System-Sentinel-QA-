"""LLM client factory — Gemini 2.5 Flash via Vertex AI.

Note: using a hosted model (Vertex AI) means prompts, requirement text, and any
retrieved source-code context leave the local environment. This is a
deliberate departure from the original data-sovereignty brief; revisit if
HPE re-imposes air-gapped execution.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_google_vertexai import ChatVertexAI
import vertexai

load_dotenv()


def get_local_llm(
    temperature: float = 0.1,
    model: str | None = None,
    json_mode: bool = False,
    location: str | None = None,
) -> ChatVertexAI:
    """Return a ChatVertexAI instance configured for Gemini models.

    Args:
        temperature: sampling temperature.
        model: override the model id (defaults to SENTINEL_LLM_MODEL or
            "gemini-2.5-flash").
        json_mode: if True, force Vertex AI to emit `application/json` so every
            response is parseable without regex scraping. Every agent that
            returns structured output should set this.
        location: override the location (defaults to VERTEX_AI_LOCATION or
            "us-central1"). Use "global" for Gemini 1.5/3.1 models.
    """
    project_id = os.getenv("VERTEX_AI_PROJECT_ID", "chessworld-test")
    location = location or os.getenv("VERTEX_AI_LOCATION", "us-central1")
    
    # Initialize Vertex AI
    vertexai.init(project=project_id, location=location)

    kwargs = {
        "model_name": model or os.getenv("SENTINEL_LLM_MODEL", "gemini-2.5-flash"),
        "temperature": temperature,
        "project": project_id,
        "location": location,
    }
    if json_mode:
        # Vertex AI structured-output switch.
        kwargs["response_mime_type"] = "application/json"

    return ChatVertexAI(**kwargs)
