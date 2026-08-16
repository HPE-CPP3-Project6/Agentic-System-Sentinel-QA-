"""LLM client factory — Gemini via Vertex AI or Google AI Studio.

Authentication:
  - Vertex AI: uses Application Default Credentials (ADC). Requires
    VERTEX_AI_PROJECT_ID and optionally VERTEX_AI_LOCATION.
  - Google AI Studio: uses GEMINI_API_KEY directly. Set LLM_PROVIDER=gemini
    in .env to use this path. No GCP project needed.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Callable, Tuple, Type

from dotenv import load_dotenv
from langchain_google_vertexai import ChatVertexAI
import vertexai

from config import get_settings

try:
    from google.api_core import exceptions as google_exceptions
    _TRANSIENT_ERRORS: Tuple[Type[BaseException], ...] = (
        google_exceptions.ResourceExhausted,    # 429
        google_exceptions.ServiceUnavailable,   # 503
        google_exceptions.DeadlineExceeded,     # 504
        google_exceptions.InternalServerError,  # 500
        google_exceptions.Aborted,              # 409
    )
except ImportError:
    _TRANSIENT_ERRORS = ()

load_dotenv()

logger = logging.getLogger(__name__)


class LLMInvocationError(RuntimeError):
    """Raised when every retry of an LLM invocation has failed."""

    def __init__(self, message: str, cause: BaseException):
        super().__init__(message)
        self.cause = cause


def invoke_with_retry(
    fn: Callable[..., Any],
    *args: Any,
    max_attempts: int = 3,
    base_delay_s: float = 2.0,
    max_delay_s: float = 30.0,
    **kwargs: Any,
) -> Any:
    """Invoke fn(*args, **kwargs) with exponential backoff on transient errors."""
    if not _TRANSIENT_ERRORS:
        return fn(*args, **kwargs)

    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except _TRANSIENT_ERRORS as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            delay = delay * (0.75 + random.random() * 0.5)
            logger.warning(
                "LLM transient error (%s) on attempt %d/%d — backing off %.1fs",
                type(exc).__name__, attempt, max_attempts, delay,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise LLMInvocationError(
        f"LLM invocation failed after {max_attempts} attempts: "
        f"{type(last_exc).__name__}: {last_exc}",
        cause=last_exc,
    )


def get_local_llm(
    temperature: float = 0.0,
    model: str | None = None,
    json_mode: bool = False,
    location: str | None = None,
    seed: int | None = 42,
):
    """Return an LLM instance configured for Gemini models.

    If LLM_PROVIDER=gemini in .env, uses Google AI Studio via GEMINI_API_KEY
    (langchain-google-genai). Otherwise falls back to Vertex AI.

    Args:
        temperature: sampling temperature. Defaults to 0.0.
        model: override model id. Defaults to SENTINEL_LLM_MODEL or
            "gemini-2.0-flash".
        json_mode: force JSON output mode.
        location: Vertex AI only — overrides VERTEX_AI_LOCATION.
        seed: fixed decoding seed for reproducibility. Pass None to disable.
    """
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    model_name = model or settings.sentinel_llm_model

    if provider == "gemini":
        # ── Google AI Studio path ──────────────────────────────────────────
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as e:
            raise RuntimeError(
                "langchain-google-genai is not installed. "
                "Run: pip install langchain-google-genai"
            ) from e

        api_key = settings.gemini_api_key.strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file."
            )

        kwargs: dict[str, Any] = {
            "model": model_name,
            "temperature": temperature,
            "google_api_key": api_key,
        }
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        if seed is not None:
            kwargs["seed"] = seed

        logger.info("Using Google AI Studio (LLM_PROVIDER=gemini), model=%s", model_name)
        return ChatGoogleGenerativeAI(**kwargs)

    else:
        # ── Vertex AI path (unchanged) ─────────────────────────────────────
        project_id = settings.vertex_ai_project_id.strip()
        if not project_id:
            raise RuntimeError(
                "VERTEX_AI_PROJECT_ID is not set. Configure it in the environment "
                "(see Backend/.env.example). There is no default project — this "
                "check exists so a misconfigured run cannot bill an unrelated GCP "
                "project."
            )
        location = location or settings.vertex_ai_location
        vertexai.init(project=project_id, location=location)

        kwargs = {
            "model_name": model_name,
            "temperature": temperature,
            "project": project_id,
            "location": location,
            "transport": "rest",
        }
        if json_mode:
            kwargs["response_mime_type"] = "application/json"
        if seed is not None:
            kwargs["seed"] = seed

        logger.info("Using Vertex AI, model=%s", model_name)
        return ChatVertexAI(**kwargs)