"""Agent D — The Executor / Healer / AIOps.

Responsibilities:
1. Runner      — executes every TestCase (functional + adversarial) and captures
                 telemetry (stack trace, console logs, HTML snapshot of the
                 Smart Task Manager UI) on failure.
2. Verdicting  — functional tests get `passed`; adversarial tests get
                 `is_vulnerable` (exploit worked) or `resilient` (app blocked it).
3. Healer      — on any failure OR confirmed vulnerability, calls the local LLM
                 with {error log + RAG source context + failed test} and emits
                 a Patch(target_file, bug_explanation, suggested_fix).
4. Posture     — writes a Security Posture summary into state.metadata:
                 attempted / resilient / vulnerable / coverage %.

The actual browser/HTTP runner is injected as a callable so this module stays
testable without a live app. A default stub is provided that always reports
failure — replace it with a Playwright-backed runner in production.

PRE_CODE mode:
  No test suite exists yet. The executor returns immediately without running
  anything, healing anything, or writing a security posture report.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.prompts import ChatPromptTemplate

from database import query_source_context
from state import ExecutionLog, Patch, ProjectState, TestCase
from utils import get_local_llm


# --------------------------------------------------------------------------- #
# Runner contract                                                             #
# --------------------------------------------------------------------------- #


@dataclass
class RunnerResult:
    """Raw output from whatever actually drives the app under test.

    For a functional test: `ok` means the expected_result was observed.
    For an adversarial test: `ok` means the attack was BLOCKED (app is resilient).
                             `ok=False` means the exploit succeeded (vulnerable).
    """
    ok: bool
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    console_logs: List[str] = field(default_factory=list)
    html_snapshot: Optional[str] = None
    exception: Optional[BaseException] = None


Runner = Callable[[TestCase], RunnerResult]


def _default_runner(tc: TestCase) -> RunnerResult:
    """Placeholder runner. Real deployments inject a Playwright-backed runner."""
    return RunnerResult(
        ok=False,
        stderr=f"No runner configured; cannot execute {tc.test_id}.",
    )


# --------------------------------------------------------------------------- #
# Execution + telemetry                                                       #
# --------------------------------------------------------------------------- #


# Upper bound on loop iterations regardless of what the generator asked for.
# REQ-002 style tests sometimes ask for 10_000 — that's fine for telemetry but
# we clamp to keep runs bounded. Override via SENTINEL_REPEAT_CAP.
_DEFAULT_REPEAT_CAP = 2000


def _repeat_cap() -> int:
    raw = os.getenv("SENTINEL_REPEAT_CAP")
    if not raw:
        return _DEFAULT_REPEAT_CAP
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_REPEAT_CAP


def _resolve_repeat(tc: TestCase) -> Tuple[int, TestCase]:
    """Extract `_repeat` sentinel from `input_data` and return (count, clean_tc).

    The clean TestCase has `_repeat` stripped so the runner never sees it.
    Returns count=1 for tests without a valid `_repeat` sentinel.
    """
    data: Any = tc.input_data
    if not isinstance(data, dict):
        return 1, tc
    raw = data.get("_repeat")
    if raw is None:
        return 1, tc
    try:
        count = int(raw)
    except (TypeError, ValueError):
        return 1, tc
    if count < 2:
        return 1, tc
    count = min(count, _repeat_cap())
    clean_data = {k: v for k, v in data.items() if k != "_repeat"}
    clean_tc = tc.model_copy(update={"input_data": clean_data})
    return count, clean_tc


def _aggregate_results(results: List[RunnerResult], is_adversarial: bool) -> RunnerResult:
    """Fold N per-request RunnerResults into one.

    Functional test aggregation: `ok` iff EVERY iteration was ok.
    Adversarial test aggregation: `ok` iff ANY iteration was blocked — a single
      blocked attempt proves the control fired at least once. If every iteration
      went through unchecked, `ok=False` → `is_vulnerable=True` downstream.
    Telemetry: stdout/stderr/console_logs concatenated with iteration markers;
      total duration summed; last non-None exception surfaced.
    """
    if is_adversarial:
        agg_ok = any(r.ok for r in results)
    else:
        agg_ok = all(r.ok for r in results)

    total_duration = sum(r.duration_ms for r in results)
    last_exc = next((r.exception for r in reversed(results) if r.exception), None)
    last_html = next((r.html_snapshot for r in reversed(results) if r.html_snapshot), None)

    stdout_parts: List[str] = []
    stderr_parts: List[str] = []
    console_all: List[str] = []
    for i, r in enumerate(results, start=1):
        if r.stdout:
            stdout_parts.append(f"[iter {i}/{len(results)}] {r.stdout}")
        if r.stderr:
            stderr_parts.append(f"[iter {i}/{len(results)}] {r.stderr}")
        if r.console_logs:
            console_all.extend(f"[iter {i}] {line}" for line in r.console_logs)

    summary = (
        f"_repeat={len(results)} ok={sum(1 for r in results if r.ok)}/"
        f"{len(results)} aggregated_ok={agg_ok}"
    )
    stdout_parts.insert(0, summary)

    return RunnerResult(
        ok=agg_ok,
        duration_ms=total_duration,
        stdout="\n".join(stdout_parts),
        stderr="\n".join(stderr_parts),
        console_logs=console_all,
        html_snapshot=last_html,
        exception=last_exc,
    )


def _run_with_repeat(tc: TestCase, runner: Runner) -> RunnerResult:
    count, clean_tc = _resolve_repeat(tc)
    if count == 1:
        return runner(clean_tc)
    results = [runner(clean_tc) for _ in range(count)]
    return _aggregate_results(results, is_adversarial=clean_tc.is_adversarial)


def _execute_single(tc: TestCase, runner: Runner) -> ExecutionLog:
    started = time.perf_counter()
    try:
        result = _run_with_repeat(tc, runner)
    except Exception as exc:  # runner itself crashed — capture everything
        return ExecutionLog(
            test_id=tc.test_id,
            status="error",
            is_adversarial=tc.is_adversarial,
            passed=False if not tc.is_adversarial else None,
            is_vulnerable=None,
            resilient=None,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stderr=str(exc),
            trace="".join(traceback.format_exception(exc)),
            exploit_target=tc.exploit_target,
        )

    if tc.is_adversarial:
        # ok = app blocked the attack
        is_vuln = not result.ok
        return ExecutionLog(
            test_id=tc.test_id,
            status="failed" if is_vuln else "passed",
            is_adversarial=True,
            is_vulnerable=is_vuln,
            resilient=result.ok,
            duration_ms=result.duration_ms,
            stdout=result.stdout,
            stderr=result.stderr,
            trace="".join(traceback.format_exception(result.exception)) if result.exception else None,
            console_logs=result.console_logs,
            html_snapshot=result.html_snapshot,
            exploit_target=tc.exploit_target,
        )

    # Functional test
    return ExecutionLog(
        test_id=tc.test_id,
        status="passed" if result.ok else "failed",
        is_adversarial=False,
        passed=result.ok,
        duration_ms=result.duration_ms,
        stdout=result.stdout,
        stderr=result.stderr,
        trace="".join(traceback.format_exception(result.exception)) if result.exception else None,
        console_logs=result.console_logs,
        html_snapshot=result.html_snapshot,
    )


# --------------------------------------------------------------------------- #
# Healer                                                                      #
# --------------------------------------------------------------------------- #


HEALER_SYSTEM_PROMPT = """You are Agent D — The Healer, an AIOps engineer for HPE's
Sentinel-QA pipeline. A test has just failed OR an OWASP exploit succeeded against
the application under test. You must propose a minimal, targeted code patch.

Rules:
1. Root-cause the failure using the Error Log, the Failed Test Case, and the
   Source Context below. Do NOT suggest silencing the test or weakening the assertion.
2. For security failures, the fix MUST defeat the attacker class (e.g.,
   parameterised queries for SQLi, output encoding + CSP for XSS, allow-lists
   for SSRF). A fix that merely filters the one literal payload is not acceptable.
3. Output STRICT JSON — no prose, no markdown fences:

{{
  "target_file": "<path from source context, best guess>",
  "bug_explanation": "<1-3 sentences on why the code fails this test>",
  "suggested_fix": "<the replacement code block, ready to paste>",
  "owasp_category": "<Axx:2021-... or null>"
}}
"""


HEALER_USER_PROMPT = """Failed test:
  id: {test_id}
  title: {title}
  action: {action}
  input_data: {input_data}
  expected_result: {expected_result}
  is_adversarial: {is_adversarial}
  exploit_target: {exploit_target}

Telemetry:
  status: {status}
  stderr: {stderr}
  trace:
{trace}
  console_logs: {console_logs}

Source context (retrieved via RAG):
----- BEGIN SOURCE CONTEXT -----
{source_context}
----- END SOURCE CONTEXT -----

Emit JSON only."""


def _parse_patch_json(raw: str) -> Dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _heal(tc: TestCase, log: ExecutionLog, llm) -> Optional[Patch]:
    rag_query = f"{tc.action} {tc.title} {' '.join(tc.source_refs)}".strip()
    snippets = query_source_context(rag_query, n_results=5)
    source_context = (
        "\n\n---\n\n".join(snippets) if snippets else "(no indexed source available)"
    )

    prompt = ChatPromptTemplate.from_messages(
        [("system", HEALER_SYSTEM_PROMPT), ("user", HEALER_USER_PROMPT)]
    )
    chain = prompt | llm
    response = chain.invoke(
        {
            "test_id": tc.test_id,
            "title": tc.title,
            "action": tc.action,
            "input_data": json.dumps(tc.input_data, default=str),
            "expected_result": tc.expected_result,
            "is_adversarial": tc.is_adversarial,
            "exploit_target": tc.exploit_target or "n/a",
            "status": log.status,
            "stderr": log.stderr or "",
            "trace": log.trace or "(none)",
            "console_logs": "\n".join(log.console_logs) or "(none)",
            "source_context": source_context,
        }
    )

    try:
        data = _parse_patch_json(response.content)
    except (json.JSONDecodeError, ValueError):
        return None

    return Patch(
        target_file=str(data.get("target_file", "unknown")),
        bug_explanation=str(data.get("bug_explanation", "")),
        suggested_fix=str(data.get("suggested_fix", "")),
        owasp_category=data.get("owasp_category") or tc.owasp_category,
        related_test_ids=[tc.test_id],
    )


# --------------------------------------------------------------------------- #
# Security posture report                                                     #
# --------------------------------------------------------------------------- #


def _security_posture(logs: List[ExecutionLog]) -> Dict[str, object]:
    adv = [l for l in logs if l.is_adversarial]
    attempted = len(adv)
    resilient = sum(1 for l in adv if l.resilient)
    vulnerable = sum(1 for l in adv if l.is_vulnerable)

    by_target: Dict[str, Dict[str, int]] = {}
    for l in adv:
        key = l.exploit_target or "unknown"
        bucket = by_target.setdefault(key, {"attempted": 0, "resilient": 0, "vulnerable": 0})
        bucket["attempted"] += 1
        if l.resilient:
            bucket["resilient"] += 1
        if l.is_vulnerable:
            bucket["vulnerable"] += 1

    return {
        "attempted": attempted,
        "resilient": resilient,
        "vulnerable": vulnerable,
        "resilience_pct": round(100 * resilient / attempted, 1) if attempted else None,
        "by_exploit_target": by_target,
    }


# --------------------------------------------------------------------------- #
# LangGraph node                                                              #
# --------------------------------------------------------------------------- #


def executor_node(
    state: ProjectState,
    *,
    runner: Runner = _default_runner,
) -> ProjectState:
    """Run every test, capture telemetry, heal failures, publish security posture.

    PRE_CODE mode: no test suite exists yet — returns immediately without
    executing, healing, or writing a security posture report.
    POST_CODE mode: unchanged — runs all tests, heals failures, reports posture.
    """

    # ------------------------------------------------------------------
    # PRE_CODE branch — no test suite exists yet, nothing to execute
    # ------------------------------------------------------------------
    if state.pipeline_mode == "PRE_CODE":
        state.metadata["executor_skipped"] = "PRE_CODE: no test suite to execute"
        return state

    # ------------------------------------------------------------------
    # POST_CODE branch — original logic, completely unchanged
    # ------------------------------------------------------------------

    state.heal_attempts += 1
    llm = get_local_llm(temperature=0.0)

    run_logs: List[ExecutionLog] = []
    new_patches: List[Patch] = []

    for tc in state.test_suite:
        log = _execute_single(tc, runner)
        run_logs.append(log)

        needs_patch = (
            (not tc.is_adversarial and log.passed is False)
            or (tc.is_adversarial and log.is_vulnerable is True)
            or log.status == "error"
        )
        if needs_patch:
            patch = _heal(tc, log, llm)
            if patch is not None:
                new_patches.append(patch)

    state.logs.extend(run_logs)
    state.suggested_patches.extend(new_patches)
    state.metadata["security_posture"] = _security_posture(run_logs)
    state.metadata["last_run_summary"] = {
        "total": len(run_logs),
        "functional_failed": sum(1 for l in run_logs if not l.is_adversarial and l.passed is False),
        "vulnerabilities_found": sum(1 for l in run_logs if l.is_vulnerable),
        "patches_proposed": len(new_patches),
        "heal_attempt": state.heal_attempts,
    }
    return state


def needs_healing(state: ProjectState) -> str:
    """Conditional edge: loop if (any functional failure OR any vulnerability)
    AND we still have heal budget."""
    if state.heal_attempts >= state.max_heal_attempts:
        return "end"

    has_functional_failure = any(
        (not l.is_adversarial) and l.passed is False for l in state.logs
    )
    has_vulnerability = any(l.is_vulnerable for l in state.logs)

    if has_functional_failure or has_vulnerability:
        return "heal"
    return "end"