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

The browser/HTTP runner is injected as a callable when no generated pytest
file is used. If ``security_compiler_generated_files`` includes a ``.py``
path, the node runs ``pytest --junitxml`` once (``pytest_runner``) unless
``SENTINEL_EXECUTOR_RUN_PYTEST=0``. Otherwise the default stub reports failure
unless a custom ``runner=`` is supplied.

PRE_CODE mode:
  No test suite exists yet. The executor returns immediately without running
  anything, healing anything, or writing a security posture report.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.prompts import ChatPromptTemplate

from agents.suite_summary import build_test_suite_summary
from database import query_source_context
from state import ExecutionLog, Patch, ProjectState, TestCase
from utils import LLMInvocationError, get_local_llm, invoke_with_retry

logger = logging.getLogger(__name__)


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
    """Default runner — explicit failure rather than silent ok=False fakery.

    The pytest path is the canonical production runner (see executor_node ->
    pytest_runner.run_pytest_generated_file). This stub only fires when:
        - SENTINEL_EXECUTOR_RUN_PYTEST=0 disables the pytest path, AND
        - the caller did NOT inject a custom runner=
    Returning ok=False here previously caused EVERY test to log as a real
    failure, which then routed the heal loop on phantom bugs and burned LLM
    tokens. Emit a real RunnerResult.error so _execute_single rolls it up as
    status='error' instead — `needs_healing` ignores error-status routed-to-heal
    via the heal_attempt filter, and the artifact reflects the configuration
    issue plainly.
    """
    return RunnerResult(
        ok=False,
        stderr=(
            f"_default_runner is a no-op; cannot execute {tc.test_id}. "
            "Either set SENTINEL_EXECUTOR_RUN_PYTEST=1 (default) so the pytest "
            "runner takes over, or inject runner= when calling executor_node()."
        ),
        exception=RuntimeError("no runner configured"),
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
the application under test. You must propose a minimal, targeted, SAFE code patch.

============================================================
HARD RULES — VIOLATIONS ARE REJECTED AT POST-PROCESS
============================================================

R1. ROOT-CAUSE THE PRODUCTION CODE, NOT THE TEST.
    Use the Error Log + Failed Test Case + Source Context to fix the real
    cause. Do NOT weaken the assertion. Do NOT silence the test.

R2. NEVER PATCH PRODUCTION TO SATISFY A MISSING TEST FIXTURE.
    If the test expects a specific user / row / token to exist, the FIX is
    a separate seed / fixture / migration file — NOT a conditional inside
    `auth.py`, `models.py`, or any production module. Specifically forbidden:
        - `if email == "test@example.com" and password == "...": create_user(...)`
        - `if user is None: user.hashed_password = hash_password(test_password)`
        - any hardcoded email / password / token / API-key literal in
          authentication, authorization, or persistence code paths.
    If the only way to make a test pass is to inject a fixture into prod
    code, the TEST is wrong — explain that in `bug_explanation` and emit
    an empty suggested_fix (the post-processor will record this as a
    "fixture-needed" note instead of a patch).

R3. NEVER OVERRIDE A FRAMEWORK'S STANDARD VALIDATION CONTRACT TO MATCH AN
    INCORRECT TEST ASSERTION.
    FastAPI/Pydantic returns 422 Unprocessable Entity for field-level
    validation failures (EmailStr, constr, min_length, regex). 400 Bad
    Request is reserved for malformed JSON or app-level rejections. If a
    test asserts `expected_status_code == 400` but the framework correctly
    returns 422 for the input, that is the test's bug — propose NOTHING
    rather than adding a custom exception handler to remap 422 -> 400.

R4. SECURITY FIXES MUST DEFEAT THE ATTACKER CLASS, NOT THE LITERAL PAYLOAD.
    A03 SQLi  → parameterised queries, not regex blocklists of `;` / `--`.
    A03 XSS   → output encoding + CSP, not blocklists of `<script>`.
    A07 brute → rate-limit + lockout, not "if attempts > 100: deny".
    A blocklist that catches the one payload but lets variants through is
    not acceptable — name the GENERAL mitigation explicitly.

R5. RESPECT PREVIOUSLY-PROPOSED PATCHES (see "Prior patch attempts" below).
    If a prior cycle proposed a patch for this same test that did NOT
    resolve the failure, propose a DIFFERENT approach — diagnose why the
    prior attempt failed, then change strategy (different file / different
    layer / different mitigation class). Do NOT re-emit a near-identical
    patch.

============================================================
OUTPUT — STRICT JSON, no prose, no markdown fences
============================================================
{{
  "target_file": "<path from source context, or empty string if no patch is safe>",
  "bug_explanation": "<1-3 sentences. If the TEST is wrong (R2 / R3), explain that here and leave suggested_fix empty>",
  "suggested_fix": "<replacement code block ready to paste, OR empty string when no safe patch exists>",
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

Prior patch attempts for THIS test in earlier heal cycles (if any):
----- BEGIN PRIOR PATCHES -----
{prior_patches}
----- END PRIOR PATCHES -----

Source context (retrieved via RAG):
----- BEGIN SOURCE CONTEXT -----
{source_context}
----- END SOURCE CONTEXT -----

Emit JSON only."""


# --------------------------------------------------------------------------- #
# Patch safety validator (NEW-5 — guardrails against backdoor patches)        #
# --------------------------------------------------------------------------- #

# Patterns that have historically appeared in unsafe Healer output. These are
# regex shapes — not literal blocklists of the values themselves — so the
# detector catches variants (different test emails, different password
# literals) without being fooled by minor token reshuffling.
_DANGEROUS_PATCH_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = []


def _compile_patterns() -> None:
    """Lazy-compile so module-import cost stays tiny."""
    import re as _re
    if _DANGEROUS_PATCH_PATTERNS:
        return
    _DANGEROUS_PATCH_PATTERNS.extend([
        # Email literal compared inside auth/validation code:
        #     if email == "test@example.com": ...
        #     if form.username == 'admin@admin.com': ...
        ("hardcoded_email_compare",
         _re.compile(r'(?i)(email|username)\s*==?\s*[\'"][^\'"\s]+@[^\'"\s]+[\'"]')),

        # Password literal in a compare:
        #     if password == "Password123": ...
        ("hardcoded_password_compare",
         _re.compile(r'(?i)(password|passwd|pwd)\s*==?\s*[\'"][^\'"\s]{4,}[\'"]')),

        # In-line creation of a User with a hardcoded password literal:
        #     User(email=..., hashed_password=hash_password("Password123"))
        ("inline_user_creation_with_literal",
         _re.compile(r'(?is)\b(User|UserCreate)\s*\([^)]{0,200}hash(_?password)?\s*\(\s*[\'"][^\'"]{4,}[\'"]')),

        # Silent password mutation — overwriting a stored hash to make a test
        # pass. This is the exact pattern from TC-REQ-004-01 in the demo
        # artifact: `user.hashed_password = hash_password(password)`.
        ("silent_password_overwrite",
         _re.compile(r'(?i)\.\s*hashed_password\s*=\s*hash_password\s*\(')),

        # Test marker leaking into prod source (TEST-ONLY, TEST_USER, etc.).
        ("test_marker_in_prod_code",
         _re.compile(r'(?i)\b(test[-_]?(only|user|fixture|hook|backdoor)|FOR_TEST)\b')),

        # API-key / token literals embedded in patch text.
        ("hardcoded_token_or_key",
         _re.compile(r'(?i)\b(api[_-]?key|secret[_-]?key|bearer)\s*=\s*[\'"][A-Za-z0-9_\-]{16,}[\'"]')),

        # Custom 422 -> 400 exception handler — the exact framework-override
        # anti-pattern from the demo artifact. Match a Pydantic
        # RequestValidationError handler that returns HTTP_400_BAD_REQUEST.
        ("pydantic_422_to_400_override",
         _re.compile(r'(?is)RequestValidationError.*?HTTP_400_BAD_REQUEST', _re.DOTALL)),
    ])


def _validate_patch_safety(suggested_fix: str, target_file: str) -> Optional[str]:
    """Return a human-readable warning if the patch matches a dangerous pattern.

    Returns None if the patch passes all checks. Returning a string does NOT
    drop the patch — the patch is still surfaced in state.suggested_patches,
    but its `safety_warning` field is populated so reviewers (and any future
    auto-merge tooling) can refuse it.

    The hard rules in the Healer prompt are the first line of defense; this
    function is the deterministic backstop for when the LLM ignores them.
    """
    _compile_patterns()
    if not suggested_fix or not suggested_fix.strip():
        return None  # empty fix is the Healer correctly opting out; not unsafe

    warnings: List[str] = []
    for name, pat in _DANGEROUS_PATCH_PATTERNS:
        m = pat.search(suggested_fix)
        if m:
            snippet = m.group(0)
            if len(snippet) > 120:
                snippet = snippet[:120] + "..."
            warnings.append(f"{name}: matched `{snippet}`")

    # Auth/config files are particularly sensitive — escalate any warning
    # that fires there.
    sensitive_paths = ("auth.py", "config.py", "security.py", "settings.py")
    target_lc = (target_file or "").lower()
    if warnings and any(p in target_lc for p in sensitive_paths):
        return (
            "UNSAFE PATCH (auth/config target) — DO NOT AUTO-MERGE. "
            + " | ".join(warnings)
        )
    if warnings:
        return "UNSAFE PATCH — review required. " + " | ".join(warnings)
    return None


# --------------------------------------------------------------------------- #
# Prior-patch awareness (H8) — feed the Healer what it already tried         #
# --------------------------------------------------------------------------- #


_UNSAFE_PREFIX = "[UNSAFE-PATCH-FLAG] "


def _patch_safety_warning(p: "Patch") -> Optional[str]:
    """Recover the safety_warning (if any) from a Patch.

    The Patch schema does NOT carry a `safety_warning` field — to stay
    compatible with the canonical state model we encode the warning inside
    `bug_explanation` with a fixed `[UNSAFE-PATCH-FLAG] ...\\n` prefix. This
    helper extracts it back out so reviewers / metadata aggregators don't
    have to grep strings.
    """
    text = p.bug_explanation or ""
    if not text.startswith(_UNSAFE_PREFIX):
        return None
    # First line carries the warning; rest is the Healer's explanation.
    first_nl = text.find("\n")
    head = text if first_nl == -1 else text[:first_nl]
    return head[len(_UNSAFE_PREFIX):].strip() or None


def _format_prior_patches(patches: List[Patch], test_id: str, max_chars: int = 3000) -> str:
    """Render prior Patches that target this test as a compact prompt block.

    Keeps the prompt under a token budget. If no prior patches exist, returns
    "(none — this is the first heal attempt for this test)" so the LLM
    doesn't see a confusing empty block.
    """
    prior = [p for p in patches if test_id in (p.related_test_ids or [])]
    if not prior:
        return "(none — this is the first heal attempt for this test)"

    blocks: List[str] = []
    for i, p in enumerate(prior, 1):
        sw = _patch_safety_warning(p)
        head = (
            f"--- Prior attempt {i} "
            f"(owasp={p.owasp_category}, "
            f"safety_warning={sw or 'none'}) ---\n"
            f"target_file: {p.target_file}\n"
            f"bug_explanation: {p.bug_explanation}\n"
            f"suggested_fix (truncated):\n{(p.suggested_fix or '')[:800]}"
        )
        blocks.append(head)

    rendered = "\n\n".join(blocks)
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars] + "\n... (truncated)"
    return rendered


def _parse_patch_json(raw: str) -> Dict[str, object]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _heal(
    tc: TestCase,
    log: ExecutionLog,
    llm,
    *,
    prior_patches: Optional[List[Patch]] = None,
    heal_attempt: Optional[int] = None,
    heal_llm_errors: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Patch]:
    rag_query = f"{tc.action} {tc.title} {' '.join(tc.source_refs)}".strip()
    snippets = query_source_context(rag_query, n_results=5)
    source_context = (
        "\n\n---\n\n".join(snippets) if snippets else "(no indexed source available)"
    )

    prior_block = _format_prior_patches(prior_patches or [], tc.test_id)

    prompt = ChatPromptTemplate.from_messages(
        [("system", HEALER_SYSTEM_PROMPT), ("user", HEALER_USER_PROMPT)]
    )
    chain = prompt | llm
    invoke_ctx = {
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
        "prior_patches": prior_block,
        "source_context": source_context,
    }
    try:
        response = invoke_with_retry(chain.invoke, invoke_ctx)
    except LLMInvocationError as exc:
        logger.error(
            "[healer] Vertex failed after retries for %s: %s",
            tc.test_id,
            exc,
        )
        if heal_llm_errors is not None:
            heal_llm_errors.append(
                {
                    "test_id": tc.test_id,
                    "heal_attempt": heal_attempt,
                    "error": str(exc),
                    "cause": f"{type(exc.cause).__name__}: {exc.cause}" if exc.cause else None,
                }
            )
        return None
    except Exception as exc:  # noqa: BLE001 — network blips must not abort the graph
        # RemoteDisconnected / Connection aborted are not in invoke_with_retry's
        # transient tuple; observed crashing POST_CODE after pytest succeeded.
        logger.error(
            "[healer] LLM call failed for %s: %s: %s",
            tc.test_id,
            type(exc).__name__,
            exc,
        )
        if heal_llm_errors is not None:
            heal_llm_errors.append(
                {
                    "test_id": tc.test_id,
                    "heal_attempt": heal_attempt,
                    "error": f"{type(exc).__name__}: {exc}",
                    "cause": None,
                }
            )
        return None

    try:
        data = _parse_patch_json(response.content)
    except (json.JSONDecodeError, ValueError):
        return None

    suggested_fix = str(data.get("suggested_fix", ""))
    target_file = str(data.get("target_file", "unknown"))
    bug_explanation = str(data.get("bug_explanation", ""))

    # Run the safety validator. Because the Patch schema does NOT carry a
    # dedicated `safety_warning` field, we encode the warning inline into
    # bug_explanation with a fixed prefix so:
    #   1. reviewers see it at the top of the explanation,
    #   2. `_patch_safety_warning(p)` can recover it later for metadata,
    #   3. no schema migration is required.
    safety_warning = _validate_patch_safety(suggested_fix, target_file)
    if safety_warning:
        bug_explanation = f"{_UNSAFE_PREFIX}{safety_warning}\n{bug_explanation}"

    return Patch(
        target_file=target_file,
        bug_explanation=bug_explanation,
        suggested_fix=suggested_fix,
        owasp_category=data.get("owasp_category") or tc.owasp_category,
        related_test_ids=[tc.test_id],
    )


def _dedup_suggested_patches(existing: List[Patch], new: List[Patch]) -> List[Patch]:
    """Replace any prior Patch that targets the same test+owasp with the new one.

    Keeps `state.suggested_patches` honest across heal cycles: when cycle 2
    proposes a new patch for `TC-REQ-004-01`, the cycle-1 patch for the same
    test is replaced rather than appended. Without this dedup the artifact
    accumulates duplicates (observed: 16 cycle-2 patches accumulated to 31
    total in exec-demo-login-post_code).

    Identity tuple: (sorted related_test_ids, owasp_category). Two patches
    that disagree on owasp_category for the same test are kept separately —
    they represent distinct hypotheses about the failure.
    """
    def key(p: Patch) -> Tuple[Tuple[str, ...], Optional[str]]:
        return (tuple(sorted(p.related_test_ids or [])), p.owasp_category)

    by_key: Dict[Tuple[Tuple[str, ...], Optional[str]], Patch] = {}
    for p in existing:
        by_key[key(p)] = p
    for p in new:
        by_key[key(p)] = p  # overwrites any prior cycle's patch for same identity
    deduped = list(by_key.values())

    # 0.3a — SECOND pass: collapse patches that propose the SAME change to the
    # SAME file, even when their related_test_ids differ. The first pass keys
    # on test id, so 7 path-param injection tests each yielding a
    # "task_id: uuid.UUID" patch survive as 7 near-identical entries
    # (observed in exec-demo-lifecycle). Group non-empty-target patches by
    # (target_file, change_intent); keep the first, fold the others' test ids
    # into related_test_ids so traceability is preserved.
    return _collapse_by_intent(deduped)


# Semantic "change intent" tokens — type annotations, status codes, and
# explicit HTTP-status constants. Two patches sharing the same intent token
# set against the same file are the same fix wearing different test ids.
_PATCH_INTENT_RE = re.compile(
    r"(\b\w+\s*:\s*uuid\.UUID\b|\buuid\.UUID\b|status\.HTTP_\d+\w*|"
    r"status_code\s*=\s*\d+|\b\w+\s*:\s*(?:int|str|UUID|bool|float)\b)",
    re.IGNORECASE,
)


def _patch_intent(p: Patch) -> frozenset:
    """Coarse semantic fingerprint of what a patch CHANGES (whitespace-stable)."""
    fix = p.suggested_fix or ""
    return frozenset(
        m.group(0).lower().replace(" ", "") for m in _PATCH_INTENT_RE.finditer(fix)
    )


def _collapse_by_intent(patches: List[Patch]) -> List[Patch]:
    """Collapse same-file same-intent patches into one (merge test ids)."""
    out: List[Patch] = []
    seen: Dict[Tuple[str, frozenset], int] = {}  # (target_file, intent) -> index in out
    for p in patches:
        tf = (p.target_file or "").strip()
        intent = _patch_intent(p)
        # Only collapse when we have BOTH a real target file AND a recognized
        # intent — otherwise we can't be confident two patches are "the same",
        # so we keep them separate (no over-merging of distinct fixes).
        if not tf or not intent:
            out.append(p)
            continue
        k = (tf, intent)
        if k in seen:
            kept = out[seen[k]]
            merged_ids = sorted(set(kept.related_test_ids or []) | set(p.related_test_ids or []))
            out[seen[k]] = kept.model_copy(update={"related_test_ids": merged_ids})
        else:
            seen[k] = len(out)
            out.append(p)
    return out


# --------------------------------------------------------------------------- #
# Security posture report                                                     #
# --------------------------------------------------------------------------- #


def _security_posture(logs: List[ExecutionLog]) -> Dict[str, object]:
    adv = [l for l in logs if l.is_adversarial]
    attempted = len(adv)
    resilient = sum(1 for l in adv if l.resilient is True)
    vulnerable = sum(1 for l in adv if l.is_vulnerable is True)

    # Two distinct failure-to-decide modes — must NOT be conflated:
    #   skipped — pytest.skip fired (no JWT, parametrize filter, etc.).
    #             The attack never ran. NOT evidence of resilience.
    #   error   — pytest_runner timeout, collect error, target unreachable.
    #             The attack tried to run and infrastructure failed.
    #             NOT evidence of resilience either — but ALSO not evidence
    #             that the test was deliberately filtered out.
    # Previous version lumped both into "skipped", which lied about how
    # much was deliberately deferred vs how much fell over.
    skipped = sum(
        1 for l in adv
        if l.resilient is None and l.is_vulnerable is None and l.status == "skipped"
    )
    errored = sum(
        1 for l in adv
        if l.resilient is None and l.is_vulnerable is None and l.status == "error"
    )
    decided = resilient + vulnerable

    by_target: Dict[str, Dict[str, int]] = {}
    for l in adv:
        key = l.exploit_target or "unknown"
        bucket = by_target.setdefault(
            key,
            {"attempted": 0, "resilient": 0, "vulnerable": 0, "skipped": 0, "errored": 0},
        )
        bucket["attempted"] += 1
        if l.resilient is True:
            bucket["resilient"] += 1
        elif l.is_vulnerable is True:
            bucket["vulnerable"] += 1
        elif l.status == "error":
            bucket["errored"] += 1
        else:
            bucket["skipped"] += 1

    return {
        "attempted": attempted,
        "resilient": resilient,
        "vulnerable": vulnerable,
        "skipped": skipped,
        "errored": errored,
        # Percentage is computed against DECIDED tests only — skipped AND
        # errored are excluded so partial runs do not understate resilience.
        "resilience_pct": round(100 * resilient / decided, 1) if decided else None,
        "by_exploit_target": by_target,
    }


# --------------------------------------------------------------------------- #
# Suite quality gate (Stage 1 — Cursor merged priority list)                  #
# --------------------------------------------------------------------------- #
#
# Background: the taskshare demo run produced an artifact with 0 generated
# tests but no explicit signal that the suite was empty — downstream readers
# (release-gate CI, dashboard, HPE reviewer) had to infer "nothing actually
# ran" from a missing executor_pytest_returncode field. That's a silent
# attestation lie: "Sentinel closed the loop" reads true even when nothing
# was attempted.
#
# This gate computes a coarse enum that sits at the top of the artifact so
# a release-gate check is one read:
#
#   NO_TESTS_GENERATED — Generator produced zero tests. Loop did not run.
#   ALL_SKIPPED        — Every test was pytest.skip'd (missing JWT, etc.).
#                        Nothing was actually exercised against the app.
#   INSUFFICIENT       — Suite ran but coverage is too thin relative to the
#                        validated requirements (heuristic floor).
#   NO_RISKS_PREDICTED — Critic flagged zero security risks; an adversarial
#                        suite would have been empty by design. Functional
#                        tests, if any, still ran. NOT a failure mode — it's
#                        an honest statement that the story has no OWASP
#                        exposure to attest against.
#   ATTESTABLE         — Normal case: a non-trivial suite ran with at least
#                        some adversarial coverage (or the story genuinely
#                        had no risks). Posture metrics are trustworthy.
#
# Floor for INSUFFICIENT: max(3, len(validated_requirements)). One test per
# AC is the bare-minimum coverage; below that the attestation isn't credible.
# We deliberately do NOT use a coverage-percent gate (that's a sharper tool
# that needs evidence we don't yet have for it).
def _suite_quality(
    *,
    test_suite_size: int,
    run_logs: List[ExecutionLog],
    validated_requirements_count: int,
    security_risks_count: int,
) -> str:
    if test_suite_size == 0:
        return "NO_TESTS_GENERATED"
    if run_logs and all(l.status == "skipped" for l in run_logs):
        return "ALL_SKIPPED"
    # Coverage floor — one test per AC, never less than 3 for tiny stories
    # so a 1-AC story still needs a real adversarial + functional + edge test.
    floor = max(3, validated_requirements_count)
    if test_suite_size < floor:
        return "INSUFFICIENT"
    # Empty-adversarial is honest when there are no risks to attack.
    if security_risks_count == 0:
        return "NO_RISKS_PREDICTED"
    return "ATTESTABLE"


# --------------------------------------------------------------------------- #
# Attestation model (v3 P0) — two axes: run_validity + coverage_quality       #
# --------------------------------------------------------------------------- #
#
# `_suite_quality` above answers "was the SUITE meaningful?" (coverage_quality).
# It is ONLY trustworthy when the run itself was valid. These helpers answer
# the orthogonal question "did we actually exercise the app?" (run_validity):
#
#   OK                     — the app was reachable and the suite behaved.
#   TARGET_UNREACHABLE     — the live API was down; tests connect-errored.
#                            Posture is meaningless (no attack ever fired).
#   FUNCTIONALLY_UNRELIABLE— too many functional failures are TEST defects
#                            (Healer opted out), not app bugs. The suite
#                            can't be trusted to attest the app.
#
# Read order: a consumer checks run_validity FIRST; only when it is OK does
# coverage_quality / resilience_pct mean anything. This kills the
# "ATTESTABLE / 100% resilient on a dead server" lie observed in
# exec-demo-lifecycle-post_code-20260530_123829 (75 ConnectErrors, still
# printed 100%).

# Signatures that a test errored because the target API was unreachable —
# not because the attack/assertion did anything. Lowercased substring match
# against the test's captured stderr/stdout/trace.
_CONNECT_ERROR_SIGNATURES = (
    "connecterror", "connection refused", "actively refused", "[errno 111]",
    "winerror 10061", "10061", "max retries exceeded", "failed to establish",
    "connecttimeout", "newconnectionerror", "connection aborted",
    "all connection attempts failed",
)

# Run is TARGET_UNREACHABLE when this fraction of EXECUTED (non-skipped) tests
# connect-errored. A flapping server might error a minority; a down server
# errors ~all. 0.40 catches "down" without tripping on a few transient errors.
_TARGET_UNREACHABLE_RATE = 0.40

# Run is FUNCTIONALLY_UNRELIABLE when this fraction of functional failures are
# Healer opt-outs (empty target_file = "the test is wrong, not the app").
# Uses the Healer's own signal rather than a hand-rolled fixture-vs-real
# classifier (which can't distinguish a fixture-404 from a real-bug 404).
_FUNCTIONAL_UNRELIABLE_RATE = 0.30


def _is_connect_error(log: ExecutionLog) -> bool:
    if log.status != "error":
        return False
    blob = " ".join(
        s for s in (log.stderr, log.trace, log.stdout) if s
    ).lower()
    return any(sig in blob for sig in _CONNECT_ERROR_SIGNATURES)


def _detect_target_unreachable(
    run_logs: List[ExecutionLog],
) -> Optional[Dict[str, Any]]:
    """Return evidence dict if the target API was unreachable, else None.

    Computed BEFORE the heal pass so healing can be skipped — patching the
    app for ConnectErrors is futile and pollutes the artifact.
    """
    executed = [l for l in run_logs if l.status != "skipped"]
    if not executed:
        return None
    connect_errs = sum(1 for l in run_logs if _is_connect_error(l))
    rate = connect_errs / len(executed)
    if rate >= _TARGET_UNREACHABLE_RATE:
        return {
            "connect_errors": connect_errs,
            "executed": len(executed),
            "connect_error_rate": round(rate, 2),
            "reason": (
                "API not reachable — connect/refused on "
                f">={int(_TARGET_UNREACHABLE_RATE * 100)}% of executed tests"
            ),
        }
    return None


def _detect_functional_unreliability(
    run_logs: List[ExecutionLog],
    new_patches: List[Patch],
) -> Optional[Dict[str, Any]]:
    """Return evidence dict if functional failures are dominated by test
    defects (Healer opt-outs), else None. Computed AFTER the heal pass."""
    func_fail = [
        l for l in run_logs
        if (not l.is_adversarial) and l.passed is False and l.verdict != "off_target"
    ]
    if not func_fail:
        return None
    fail_ids = {l.test_id for l in func_fail}
    optout_ids: set = set()
    for p in new_patches:
        if (p.target_file or "").strip():
            continue  # actionable patch — Healer believes it's a real app bug
        for tid in (p.related_test_ids or []):
            if tid in fail_ids:
                optout_ids.add(tid)
    ratio = len(optout_ids) / len(func_fail)
    if ratio >= _FUNCTIONAL_UNRELIABLE_RATE:
        return {
            "functional_failures": len(func_fail),
            "test_defect_failures": len(optout_ids),
            "defect_ratio": round(ratio, 2),
            "reason": (
                "majority of functional failures are Healer-flagged test "
                "defects (empty target_file), not app bugs"
            ),
        }
    return None


# 0.3b — Healer backstop: an id-route injection probe that the app answered
# with 404 ("no such row / not yours") was safely neutralized. 0.3c already
# makes 404 an acceptable status for these (so they pass), but if one still
# reaches the Healer (e.g. routed via an error), we must NOT propose an app
# patch — 404 is correct, the test merely wanted a different 4xx. Convert any
# such patch to an opt-out (empty target_file) with an explanation.
_ID_ROUTE_TEMPLATE_RE = re.compile(r"/\{[a-zA-Z_]\w*\}")
_ID_ROUTE_UUID_RE = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _is_safe_404_optout(tc: TestCase, log: ExecutionLog) -> bool:
    if not tc.is_adversarial:
        return False
    path = tc.bound_path or ""
    is_id_route = bool(_ID_ROUTE_TEMPLATE_RE.search(path)) or bool(_ID_ROUTE_UUID_RE.search(path))
    if not is_id_route:
        return False
    blob = " ".join(s for s in (log.stderr, log.stdout, log.trace) if s)
    return "404" in blob


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
        # Stage 1: stamp suite_quality on the PRE_CODE branch too so the
        # artifact has a single field a release-gate can read regardless of
        # which mode produced it. PRE_CODE is by construction "no executable
        # suite yet" — emit NO_TESTS_GENERATED rather than leaving the field
        # absent (which previously read as "looks ok").
        state.metadata["suite_quality"] = "NO_TESTS_GENERATED"
        return state

    # ------------------------------------------------------------------
    # POST_CODE branch — original logic, completely unchanged
    # ------------------------------------------------------------------

    state.heal_attempts += 1
    llm = get_local_llm(temperature=0.0)

    run_logs: List[ExecutionLog] = []
    new_patches: List[Patch] = []

    paths = list(state.metadata.get("security_compiler_generated_files") or [])
    py_candidates = [Path(p) for p in reversed(paths) if str(p).endswith(".py")]
    py_file = next((p for p in py_candidates if p.is_file()), None)
    run_pytest = os.getenv("SENTINEL_EXECUTOR_RUN_PYTEST", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    if py_file and run_pytest and state.test_suite:
        from .pytest_runner import run_pytest_generated_file

        run_logs, rc, out, err = run_pytest_generated_file(
            list(state.test_suite),
            py_file,
            surface_map=state.surface_map,  # Layer A — tier-0 off-target gate
        )
        state.metadata["executor_pytest_file"] = str(py_file.resolve())
        state.metadata["executor_pytest_returncode"] = rc
        state.metadata["executor_pytest_stdout_tail"] = out[-4000:] if len(out) > 4000 else out
        state.metadata["executor_pytest_stderr_tail"] = err[-4000:] if len(err) > 4000 else err
        # Stage 6 (Cursor merged priority list) — breakdown next to the rc.
        # Background: returncode alone is ambiguous. rc=1 can mean "1 of 30
        # tests asserted a vulnerability" OR "pytest collect error, nothing
        # ran". The reviewer had to crack open stdout_tail to tell. Surfacing
        # the per-status counts inline removes that step. The breakdown is
        # computed from run_logs (which the runner has already mapped 1:1
        # with state.test_suite) so it's authoritative.
        state.metadata["executor_pytest_tests_total"] = len(run_logs)
        state.metadata["executor_pytest_passed"] = sum(
            1 for l in run_logs if l.status == "passed"
        )
        state.metadata["executor_pytest_failed"] = sum(
            1 for l in run_logs if l.status == "failed"
        )
        state.metadata["executor_pytest_errored"] = sum(
            1 for l in run_logs if l.status == "error"
        )
        state.metadata["executor_pytest_skipped"] = sum(
            1 for l in run_logs if l.status == "skipped"
        )
        if rc == -1:
            # pytest_runner signals subprocess.TimeoutExpired with rc=-1 and
            # synthesises one error log per test so the graph can heal once
            # instead of crashing.
            state.metadata["executor_pytest_timeout"] = True
    else:
        if py_file and not run_pytest:
            state.metadata["executor_pytest_skipped"] = "SENTINEL_EXECUTOR_RUN_PYTEST disabled"
        for tc in state.test_suite:
            run_logs.append(_execute_single(tc, runner))

    # Stamp every new log with the current heal attempt. `needs_healing` filters
    # on this so prior-run failures (still present in state.logs after extend)
    # cannot keep routing "heal" after the current cycle has actually cleared.
    for log in run_logs:
        log.heal_attempt = state.heal_attempts

    # 0.5 — TARGET_UNREACHABLE guard. If the live API is down, ~every test
    # connect-errors. Healing those is futile (you can't patch the app into
    # being reachable) and the posture would be a lie (no attack ever fired).
    # Detect BEFORE the heal pass and short-circuit healing when unreachable.
    _unreachable = _detect_target_unreachable(run_logs)
    if _unreachable is not None:
        state.metadata["heal_suppressed_reason"] = "target_unreachable"

    # Heal pass — runs for BOTH the pytest path and the injected-runner path.
    # run_logs is aligned 1:1 with state.test_suite in either branch (the pytest
    # runner emits one log per TestCase in order; so does the stub loop above).
    # H8: we pass the existing state.suggested_patches in so _heal can show the
    # Healer LLM what was tried (and failed) in prior cycles — stops it from
    # re-proposing near-identical patches each iteration.
    heal_llm_errors: List[Dict[str, Any]] = []
    for tc, log in zip(state.test_suite, run_logs):
        # 0.5 — when the target is unreachable, skip the heal pass entirely.
        # Every "failure" is a ConnectError; the Healer would emit garbage
        # patches chasing connectivity (observed: 104 patches on a dead
        # server). Leave new_patches empty.
        if _unreachable is not None:
            break
        # Layer A — off-target tests do NOT trigger the Healer. The pytest
        # outcome is semantically null (test was outside the bound surface);
        # asking the Healer to patch the app would chase phantoms. This
        # gate works in concert with tier 0 in pytest_runner — together
        # they ensure neither posture math nor heal logic acts on a test
        # the SurfaceMap already disqualified.
        if log.verdict == "off_target":
            continue
        needs_patch = (
            (not tc.is_adversarial and log.passed is False)
            or (tc.is_adversarial and log.is_vulnerable is True)
            or log.status == "error"
        )
        if needs_patch:
            patch = _heal(
                tc, log, llm,
                prior_patches=list(state.suggested_patches),
                heal_attempt=state.heal_attempts,
                heal_llm_errors=heal_llm_errors,
            )
            if patch is not None:
                # 0.3b backstop — id-route injection neutralized by 404 is
                # safe; never ship an app patch for it. Convert to opt-out.
                if (p_tf := (patch.target_file or "").strip()) and _is_safe_404_optout(tc, log):
                    patch = patch.model_copy(update={
                        "target_file": "",
                        "suggested_fix": "",
                        "bug_explanation": (
                            "[0.3b] id-route injection neutralized with 404 "
                            "(no such row / not owned) — app is safe; no patch. "
                            + (patch.bug_explanation or "")
                        ),
                    })
                    state.metadata.setdefault("healer_404_optouts", []).append({
                        "test_id": tc.test_id, "bound_path": tc.bound_path,
                        "was_target": p_tf,
                    })
                new_patches.append(patch)

    if heal_llm_errors:
        prior_errs = list(state.metadata.get("heal_llm_errors") or [])
        prior_errs.extend(heal_llm_errors)
        state.metadata["heal_llm_errors"] = prior_errs

    state.logs.extend(run_logs)

    # P0-6 (Cursor) — QUARANTINE unsafe patches BEFORE dedup.
    # Previous behavior: state.suggested_patches contained every Healer
    # proposal including those tagged [UNSAFE-PATCH-FLAG]. A downstream
    # "apply suggested patches" workflow would happily ship backdoors,
    # 422→400 framework overrides, and silent password-hash overwrites.
    # Annotation is not blocking. Now: flagged patches are routed to
    # state.metadata["quarantined_patches"] and DROPPED from
    # state.suggested_patches. The dashboard / artifact can show both,
    # but anyone iterating state.suggested_patches as "patches to apply"
    # only sees the clean set.
    clean_patches: List[Patch] = []
    quarantined: List[Tuple[Patch, str]] = []
    for p in new_patches:
        sw = _patch_safety_warning(p)
        if sw:
            quarantined.append((p, sw))
        else:
            clean_patches.append(p)

    # NEW-3 + H3: dedup by (related_test_ids, owasp) so cycle 2's patch for
    # the same failing test REPLACES the cycle 1 patch rather than being
    # appended next to it. Demo-artifact bug: 16 cycle-2 patches accumulated
    # to 31 total because of the prior naive extend.
    state.suggested_patches = _dedup_suggested_patches(
        list(state.suggested_patches), clean_patches,
    )

    # Quarantined patches accumulate across cycles in metadata too, but
    # NEVER enter state.suggested_patches.
    if quarantined:
        prior_q = list(state.metadata.get("quarantined_patches") or [])
        for p, warning in quarantined:
            prior_q.append({
                "test_id": (p.related_test_ids or [None])[0],
                "target_file": p.target_file,
                "owasp_category": p.owasp_category,
                "warning": warning,
                "bug_explanation": p.bug_explanation,
                "suggested_fix_preview": (p.suggested_fix or "")[:400],
                "heal_attempt": state.heal_attempts,
            })
        state.metadata["quarantined_patches"] = prior_q
        # Legacy field kept for back-compat with dashboards that already key on it.
        state.metadata["unsafe_patch_warnings"] = [
            {
                "test_id": (p.related_test_ids or [None])[0],
                "target_file": p.target_file,
                "warning": warning,
            }
            for p, warning in quarantined
        ]

    _posture = _security_posture(run_logs)
    state.metadata["test_suite_summary"] = build_test_suite_summary(
        list(state.test_suite),
        run_logs,
        surface_map=state.surface_map or None,
    )

    # v3 P0 — TWO-AXIS attestation.
    #
    # coverage_quality: "was the suite meaningful?" (only trusted if run is OK)
    # run_validity:     "did we actually exercise the app?"
    #
    # `suite_quality` is kept as a deprecated alias of coverage_quality for
    # one release so existing dashboards/CI keyed on it don't break.
    _coverage_quality = _suite_quality(
        test_suite_size=len(state.test_suite),
        run_logs=run_logs,
        validated_requirements_count=len(state.validated_requirements),
        security_risks_count=len(state.security_risks),
    )
    state.metadata["coverage_quality"] = _coverage_quality
    state.metadata["suite_quality"] = _coverage_quality  # deprecated alias

    # run_validity: TARGET_UNREACHABLE (pre-heal) wins; else check functional
    # reliability (post-heal, from Healer opt-out ratio); else OK.
    if _unreachable is not None:
        state.metadata["run_validity"] = "TARGET_UNREACHABLE"
        state.metadata["run_validity_evidence"] = _unreachable
    else:
        _unreliable = _detect_functional_unreliability(run_logs, new_patches)
        if _unreliable is not None:
            state.metadata["run_validity"] = "FUNCTIONALLY_UNRELIABLE"
            state.metadata["run_validity_evidence"] = _unreliable
        else:
            state.metadata["run_validity"] = "OK"

    # Posture is only trustworthy when run_validity == OK. When it isn't, keep
    # the RAW counts for forensics but suppress the headline resilience_pct so
    # no consumer can quote "100% resilient" off a dead-target / unreliable run.
    if state.metadata["run_validity"] != "OK":
        _posture["resilience_pct"] = None
        _posture["suppressed"] = state.metadata["run_validity"]
    state.metadata["security_posture"] = _posture
    # Stage 5 (Cursor merged priority list) — actionable-patch count for the
    # current cycle. A "patch" with empty target_file is a Healer opt-out
    # (the LLM judged the failure unfixable / out-of-scope). If every new
    # patch this cycle is an opt-out, looping again will deterministically
    # produce more opt-outs and burn the heal budget on no-ops. needs_healing
    # reads this to short-circuit the cycle.
    _actionable_this_cycle = sum(
        1 for p in new_patches if (p.target_file or "").strip()
    )
    state.metadata["last_cycle_patches_total"] = len(new_patches)
    state.metadata["last_cycle_patches_actionable"] = _actionable_this_cycle
    state.metadata["last_run_summary"] = {
        "total": len(run_logs),
        "functional_failed": sum(1 for l in run_logs if not l.is_adversarial and l.passed is False),
        "vulnerabilities_found": sum(1 for l in run_logs if l.is_vulnerable),
        "patches_proposed": len(new_patches),
        "patches_clean": len(clean_patches),
        "patches_quarantined": len(quarantined),
        # Legacy alias kept so existing reports / tests don't break.
        "patches_flagged_unsafe": len(quarantined),
        "heal_attempt": state.heal_attempts,
    }
    return state


def needs_healing(state: ProjectState) -> str:
    """Conditional edge: loop if (any functional failure OR any vulnerability)
    in the MOST RECENT run AND we still have heal budget AND the Healer has
    something actionable to propose.

    Filters on `heal_attempt` so a failure from attempt N-1 (still present in
    state.logs because we extend rather than replace) cannot keep routing back
    to "heal" after attempt N has actually cleared the problem.

    Stage 5 (Cursor merged priority list) — early-exit when every patch this
    cycle was a Healer opt-out (target_file="").
    Background: org-story demo (exec-demo-org-post_code) burned both heal
    cycles on the same opt-out — Healer kept declining to patch the one
    failing test, but the loop ran twice anyway because needs_healing only
    looked at "is there a failure?". Now we also ask "did the Healer give
    us anything we could actually apply?" — if not, looping is provably
    wasted work.
    """
    if state.heal_attempts >= state.max_heal_attempts:
        return "end"

    current = state.heal_attempts
    # Layer A — off-target tests are excluded from heal triggers. They
    # didn't observe anything admissible about the requirement, so neither
    # a "functional failure" nor a "vulnerability" reading is justified.
    has_functional_failure = any(
        (not l.is_adversarial) and l.passed is False
        and l.heal_attempt == current and l.verdict != "off_target"
        for l in state.logs
    )
    has_vulnerability = any(
        l.is_vulnerable and l.heal_attempt == current and l.verdict != "off_target"
        for l in state.logs
    )

    if not (has_functional_failure or has_vulnerability):
        return "end"

    # Stage 5: actionable-patch gate. A cycle where the Healer attempted
    # patches but every single one is a no-op (empty target_file) cannot
    # make progress by re-running — the next iteration will hit the same
    # opt-out path. Only fires when patches were attempted (>0) AND none
    # were actionable; if patches_total == 0 we never invoked the Healer
    # (no needs_patch branch matched), which means the failures are
    # outside the Healer's reach for a different reason — keep the
    # original behaviour and let the heal-budget cap stop the loop.
    patches_total = state.metadata.get("last_cycle_patches_total") or 0
    patches_actionable = state.metadata.get("last_cycle_patches_actionable") or 0
    if patches_total > 0 and patches_actionable == 0:
        state.metadata["heal_loop_early_exit"] = (
            "all_healer_proposals_were_opt_outs"
        )
        return "end"

    return "heal"