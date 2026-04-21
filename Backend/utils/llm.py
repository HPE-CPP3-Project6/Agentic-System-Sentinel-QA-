"""LLM client factory — Gemini 2.5 Flash via Vertex AI.

Note: using a hosted model (Vertex AI) means prompts, requirement text, and any
retrieved source-code context leave the local environment. This is a
deliberate departure from the original data-sovereignty brief; revisit if
HPE re-imposes air-gapped execution.
"""

from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Callable, Tuple, Type

from dotenv import load_dotenv
from langchain_google_vertexai import ChatVertexAI
import vertexai

try:
    from google.api_core import exceptions as google_exceptions
    _TRANSIENT_ERRORS: Tuple[Type[BaseException], ...] = (
        google_exceptions.ResourceExhausted,   # 429
        google_exceptions.ServiceUnavailable,  # 503
        google_exceptions.DeadlineExceeded,    # 504
        google_exceptions.InternalServerError,  # 500 on transient backend hiccups
        google_exceptions.Aborted,             # 409 from concurrent contention
    )
except ImportError:
    _TRANSIENT_ERRORS = ()

load_dotenv()

logger = logging.getLogger(__name__)


class LLMInvocationError(RuntimeError):
    """Raised when every retry of an LLM invocation has failed.

    Carries the last transient exception so callers can surface details
    (HTTP status, quota project, retry-after) in coverage_gap reasons.
    """

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
    """Invoke `fn(*args, **kwargs)` with exponential backoff on transient errors.

    Retries only on Google API transient errors (429 ResourceExhausted,
    503 ServiceUnavailable, 504 DeadlineExceeded, 500, 409 Aborted).
    Non-transient errors (parse errors, auth errors, quota project misconfig)
    surface immediately so they are diagnosed, not masked.

    Raises `LLMInvocationError` if `max_attempts` retries all fail — generator
    callers convert this to a per-requirement coverage_gap rather than
    crashing the whole run.
    """
    if not _TRANSIENT_ERRORS:
        # google-api-core not importable; cannot classify — just pass through.
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
            # Jitter prevents thundering herd when multiple requirements hit
            # the same quota window.
            delay = delay * (0.75 + random.random() * 0.5)
            logger.warning(
                "LLM transient error (%s) on attempt %d/%d — backing off %.1fs",
                type(exc).__name__, attempt, max_attempts, delay,
            )
            time.sleep(delay)

    assert last_exc is not None  # unreachable if max_attempts >= 1
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
) -> ChatVertexAI:
    """Return a ChatVertexAI instance configured for Gemini models.

    Args:
        temperature: sampling temperature. Defaults to 0.0 for deterministic output.
        model: override the model id (defaults to SENTINEL_LLM_MODEL or
            "gemini-2.5-flash").
        json_mode: if True, force Vertex AI to emit `application/json` so every
            response is parseable without regex scraping. Every agent that
            returns structured output should set this.
        location: override the location (defaults to VERTEX_AI_LOCATION or
            "us-central1"). Use "global" for Gemini 1.5/3.1 models.
        seed: fixed decoding seed. Combined with temperature=0.0 this pins
            outputs run-to-run on the same prompt. Pass None to disable.
    """
    project_id = os.getenv("VERTEX_AI_PROJECT_ID", "chessworld-test")
    location = location or os.getenv("VERTEX_AI_LOCATION", "us-central1")

    vertexai.init(project=project_id, location=location)

    kwargs = {
        "model_name": model or os.getenv("SENTINEL_LLM_MODEL", "gemini-2.5-flash"),
        "temperature": temperature,
        "project": project_id,
        "location": location,
    }
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    if seed is not None:
        kwargs["seed"] = seed

    return ChatVertexAI(**kwargs)
