"""Prometheus metrics — central registry of custom collectors.

Mirrors how :mod:`obs` centralizes logging: every custom time-series the app
exposes is declared here once, on the default global registry, so the
``prometheus-fastapi-instrumentator`` ``/metrics`` endpoint (wired in
``shim/app.py``) publishes them alongside the auto-generated HTTP RED metrics.

All collectors are cheap and exception-free. Recording sites should treat
metrics as best-effort: a metric call must never break a pipeline run.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Pipeline runs ────────────────────────────────────────────────────────────
RUNS_TOTAL = Counter(
    "sentinel_runs_total",
    "Pipeline runs by mode and terminal status.",
    ["mode", "status"],
)
RUNS_IN_PROGRESS = Gauge(
    "sentinel_runs_in_progress",
    "Pipeline runs currently executing.",
)
RUN_DURATION = Histogram(
    "sentinel_run_duration_seconds",
    "End-to-end run wall time.",
    ["mode"],
    buckets=(5, 15, 30, 60, 120, 300, 600, 1200),
)
NODE_DURATION = Histogram(
    "sentinel_node_duration_seconds",
    "Per-node wall time.",
    ["node"],
    buckets=(1, 5, 15, 30, 60, 120, 300),
)
RESILIENCE_PCT = Gauge(
    "sentinel_last_resilience_pct",
    "Resilience %% of the most recently completed run.",
)
VERDICTS_TOTAL = Counter(
    "sentinel_verdicts_total",
    "Test verdicts emitted across runs.",
    ["verdict"],
)
RUN_FAILURES_TOTAL = Counter(
    "sentinel_run_failures_total",
    "Failed runs by error code.",
    ["error_code"],
)

# ── LLM cost & latency ───────────────────────────────────────────────────────
LLM_LATENCY = Histogram(
    "sentinel_llm_request_seconds",
    "Gemini call latency.",
    ["model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 60),
)
LLM_REQUESTS_TOTAL = Counter(
    "sentinel_llm_requests_total",
    "LLM calls by model and outcome.",
    ["model", "outcome"],
)
LLM_TOKENS_TOTAL = Counter(
    "sentinel_llm_tokens_total",
    "LLM tokens consumed (kind=prompt|completion).",
    ["model", "kind"],
)
