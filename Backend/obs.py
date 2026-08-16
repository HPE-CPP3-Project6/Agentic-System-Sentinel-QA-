"""Structured (JSON) logging + request/run correlation IDs.

Observability basics for the API service: every log line is emitted as JSON
(ready for Splunk / ELK / Datadog ingestion) and carries a correlation id —
``request_id`` for an HTTP request, ``run_id`` for a pipeline run — propagated
via ``contextvars`` so it threads through the shim's worker threads and every
module's stdlib logger without manual plumbing.

Entry points call :func:`configure_logging` once; request/run scopes call
:func:`set_request_id` / :func:`set_run_id`.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

# python-json-logger renamed its module path in v3; support both.
try:  # v3+
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # v2
    from pythonjsonlogger.jsonlogger import JsonFormatter

# Correlation ids, defaulting to "-" so a log line outside any request/run still
# formats cleanly.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
run_id_var: ContextVar[str] = ContextVar("run_id", default="-")


class _CorrelationFilter(logging.Filter):
    """Attach the current request_id / run_id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = request_id_var.get()
        record.run_id = run_id_var.get()
        return True


_configured = False


def configure_logging(level: str | None = None) -> None:
    """Install a single JSON stderr handler on the root logger (idempotent).

    Level comes from the argument, else ``settings.sentinel_log_level``, else
    INFO. Replaces any pre-existing handlers (e.g. a prior ``basicConfig``).
    """
    global _configured
    if level is None:
        try:
            from config import get_settings

            level = get_settings().sentinel_log_level
        except Exception:
            level = "INFO"

    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_CorrelationFilter())
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(request_id)s %(run_id)s %(message)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
            json_ensure_ascii=False,
        )
    )
    root.addHandler(handler)
    _configured = True


def new_request_id() -> str:
    """A fresh short correlation id."""
    return uuid.uuid4().hex[:12]


def set_request_id(value: str) -> None:
    request_id_var.set(value)


def set_run_id(value: str) -> None:
    run_id_var.set(value)
