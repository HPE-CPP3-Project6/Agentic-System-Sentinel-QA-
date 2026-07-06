"""Run Security+Compiler pytest output and map JUnit XML → ExecutionLog rows.

Wires generated `test_sentinel_api_generated.py` into the Executor when
`security_compiler_generated_files` is present. Disable with
`SENTINEL_EXECUTOR_RUN_PYTEST=0` to use the injected per-TestCase runner only.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from state import ExecutionLog, SurfaceBinding, TestCase, _legacy_fields_from_verdict

from ._paths import _paths_match_any
from .attestation import (
    adversarial_verdict_on_fail,
    adversarial_verdict_on_pass,
    infer_attestation_mode,
    stamp_attestation_mode,
)
from .security_compiler import slug_from_test_id

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Env allowlist for the generated-pytest subprocess. The test file is
# LLM-shaped code; it must not inherit cloud credentials (GCP ADC path,
# Gemini API keys) or anything else it doesn't need. It DOES need:
#   - OS plumbing (PATH, TEMP, SYSTEMROOT — Windows breaks without these)
#   - Python/venv resolution
#   - SENTINEL_* (base URL + bearer token, loaded via Backend/.env anyway)
#   - TLS overrides for corp proxies, when present
_SUBPROCESS_ENV_KEYS = {
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME",
    "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "HTTPX_SSL_CERT",
}
_SUBPROCESS_ENV_PREFIXES = ("SENTINEL_", "PYTEST_", "PYTHON")


def _subprocess_env() -> Dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if k.upper() in _SUBPROCESS_ENV_KEYS
        or k.upper().startswith(_SUBPROCESS_ENV_PREFIXES)
    }


# P0-1 (Cursor) — content-aware adversarial verdict.
#
# Background: prior version flipped is_vulnerable=True on ANY adversarial
# pytest fail. That includes fixture-pollution 409s, "test expected 400 but
# app correctly returned 422" misexpectations, and crashes. Result: in
# exec-demo-login-post_code-20260528_163728 26 of 26 A03 findings were
# false positives. The pipeline reported 18.8% resilience when the real
# posture was ~94%.
#
# The Jinja template embeds two things into every assertion message:
#   - the actual response status code (after "got ")
#   - up to 800 chars of response body (after "excerpt: ")
# We parse both back out and combine with the TestCase's signature fields
# and the route's per-endpoint exploit-success semantics to make a verdict.
#
# Stage-1 follow-up (per-route semantics):
#   exec-demo-login-post_code-20260528_202228 surfaced 1 false-positive
#   "vulnerable" on TC-REQ-003-03 — a /register test that POSTed a SQLi
#   string as the PASSWORD field. The app correctly bcrypt-hashed the
#   value before any DB query (201 Created), neutralizing the attack.
#   The blanket EXPLOIT_SUCCESS_STATUSES = {200, 201} flipped it to
#   vulnerable anyway. `_is_exploit_success_status(tc, status)` now
#   disambiguates by route:
#     POST /login   200 → exploit (bearer token issued = auth bypass)
#     POST /register 201 → NOT automatic exploit (input safely processed;
#                          only flag if forbidden content leaks)
#     other routes  200 / 201 → exploit (conservative default)
_GOT_STATUS_RE = re.compile(r"got\s+(\d{3})\b")
_FORBIDDEN_HIT_RE = re.compile(r"Forbidden response fragment found", re.IGNORECASE)
# Default fallback — only consulted when the route is unknown / can't be
# extracted. Keeping {200, 201} preserves the conservative default for
# untyped routes.
_DEFAULT_EXPLOIT_SUCCESS_STATUSES = {200, 201}

# Extracts the path from a `tc.action` string of the form "POST /login ..."
# Tolerant of casing and lacking method ("/login something").
_ACTION_PATH_RE = re.compile(r"(/[A-Za-z0-9_\-./]+)")
_ACTION_METHOD_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b", re.IGNORECASE)


def _is_exploit_success_status(tc: TestCase, status_code: int) -> bool:
    """Per-METHOD per-route mapping: does `status_code` indicate the attack got through?

    Stage 2 (Cursor merged priority list) — method-awareness.
    Background: exec-demo-search-post_code surfaced 8 false-positive
    "vulnerable" verdicts on GET /tasks/?title=<script>... tests. The app
    correctly returned 200 with an empty list (input sanitized / no match),
    but the prior blanket `{200, 201}` fallback flagged the run as exploited.
    GET on a read/list endpoint returning 200 PROVES NOTHING about
    exploitability — the only evidence of a real attack hit is the response
    body, which tier 1 (forbidden-stamp) and tier 2 (excerpt scan) already
    cover. So GET 200 must NOT auto-flag.

    Rules (highest-specificity first):

    Per-route overrides (any method):
      POST /login     200 → exploit  (only success path issues a JWT)
      POST /register  201 → NOT exploit  (bcrypt already neutralised SQLi-
                                          as-password; body-leak caught above)
      /logout         any → NOT exploit  (success is the normal flow)

    Method-level defaults (when no route override matches):
      GET / HEAD / OPTIONS → NEVER exploit on 2xx alone.
        Rationale: read endpoints returning a 200 with a filtered/empty
        response are doing the right thing. A real leak would already have
        been caught by tier 1/2 above. Without this rule, every GET-list
        adversarial test that exercises query-param escaping flips
        false-positive.

      POST / PUT / PATCH / DELETE → 200/201 stays in the exploit set.
        Mutating verbs on an unknown route with a 2xx response could be IDOR
        write-success (the attacker's row hit the DB). Keep conservative.

    Unknown method (couldn't parse from tc.action) → conservative default.

    Stage 2 follow-up (observed exec-demo-search-post_code-20260528_221024):
    The original implementation parsed method/path from a single regex on
    tc.action. The Generator's adversarial actions like "Inject SQLi probe
    into search query" lack the literal verb, so method="" and the unknown-
    method fallback flagged every 200 as exploit — 14/14 search-story
    adversarial tests came back vulnerable when the app was actually
    resilient. Now we delegate to the Compiler's 4-tier
    `_method_path_from_action` (action regex → title regex → bare path →
    input_data heuristic) — the same function the Compiler uses to populate
    `tc.method` for the pytest template. Both sides now agree on method/path.
    """
    # Local import to avoid a top-level circular import (security_compiler
    # imports from this module transitively in some build configs).
    from .security_compiler import _method_path_from_action

    method, path, _err = _method_path_from_action(
        tc.action or "",
        title=tc.title or "",
        input_data=tc.input_data,
    )
    method = (method or "").upper()
    path = (path or "").rstrip("/").lower()

    # Per-route overrides — highest specificity, win regardless of method.
    if path.endswith("/login"):
        return status_code == 200  # token issuance = bypass
    if path.endswith("/register"):
        # Row creation is not exploit evidence on its own; tier 1/2 catch
        # the case where the response body actually leaks something.
        return False
    if path.endswith("/logout"):
        return False  # logout always succeeds; never an "exploit"

    # Method-level defaults.
    #
    # Safe-method 2xx is NOT exploit evidence. A search endpoint returning
    # 200 with [] for a SQLi-flavoured query is doing exactly what it
    # should. Any real leak would have been caught by the forbidden-content
    # tiers above this in _classify_adversarial_failure.
    if method in ("GET", "HEAD", "OPTIONS"):
        return False

    # Mutating verbs on unknown routes — keep the conservative default so
    # an unauthenticated PUT/DELETE that the app shouldn't have accepted
    # still flags. Tier 1/2 may already have caught a body leak; this
    # catches the silent-success case.
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        return status_code in _DEFAULT_EXPLOIT_SUCCESS_STATUSES

    # Unknown method — fall back to the conservative default rather than
    # silently classifying as resilient. Better to over-flag here than to
    # paper over a real bug in tc.action parsing.
    return status_code in _DEFAULT_EXPLOIT_SUCCESS_STATUSES


# FastAPI/Pydantic validation-error envelope signature. A 422 body of the
# form {"detail":[{"loc":["body","email"],"type":"...","msg":"..."}]} echoes
# the REQUEST field names back — so a forbidden keyword like "email" matches
# the structural reflection, not a leak. Observed r_274ae9ee: TC-REQ-002-01
# got 422 (oversized email correctly rejected), but B2 matched "email" inside
# the validation envelope and false-flagged it vulnerable.
_VALIDATION_ENVELOPE_RE = re.compile(r'"detail"\s*:\s*\[\s*\{[^]]*"loc"\s*:', re.DOTALL)


def _is_validation_error_rejection(status: int, detail: str) -> bool:
    """True when the response is a 4xx whose body is a Pydantic/FastAPI
    validation-error envelope — i.e. the attack was neutralized AT the
    validation layer and the body only reflects request field names."""
    if not (400 <= status <= 499):
        return False
    return bool(_VALIDATION_ENVELOPE_RE.search(detail or ""))


def _body_evidence_says_vulnerable(tc: TestCase, detail: str) -> bool:
    """Independent body-evidence check — fires on hard exploit signals.

    These tiers detect *response-body* evidence of compromise that is
    independent of the attestation cascade:

      • Tier B1 — pytest's _assert_forbidden helper stamped a
        FORBIDDEN_HIT marker in the assertion detail.
      • Tier B2 — the response excerpt contains any of the test's
        ``forbidden_response_content`` keywords (SQL fragments, stack
        frames, leaked email markers).
      • Tier B3 — the actual HTTP status hit a per-route exploit-success
        code (e.g. /tasks/{other_user_id} returning 200 instead of 403).

    Each tier is a HARD signal that the body shows the attack worked —
    they can promote ``inconclusive`` to ``vulnerable`` and override a
    cascade ``resilient`` (the cascade said "defense held" but the body
    proves otherwise). They never demote ``vulnerable`` to anything.
    """
    # B1 — explicit forbidden-hit marker from the pytest helper always wins;
    # the helper only stamps it on an actual matched fragment, not structure.
    if _FORBIDDEN_HIT_RE.search(detail or ""):
        return True

    m = _GOT_STATUS_RE.search(detail or "")
    actual = -1
    if m:
        try:
            actual = int(m.group(1))
        except ValueError:
            actual = -1

    # B2 — raw forbidden-keyword scan. Suppressed when the response is a 4xx
    # validation-error rejection: that envelope reflects request field names
    # (loc/type/msg), so a keyword like "email" matches structure, not a leak.
    # A genuine data leak surfaces on a 2xx success or a 500 stack trace —
    # both still caught (B2 below on those, B3 on exploit-success status, B1
    # on stamped fragments).
    if not (actual >= 0 and _is_validation_error_rejection(actual, detail)):
        excerpt_lc = (detail or "").lower()
        for kw in tc.forbidden_response_content or []:
            if kw and kw.lower() in excerpt_lc:
                return True

    # B3 — actual status hit a per-route exploit-success code.
    if actual >= 0 and _is_exploit_success_status(tc, actual):
        return True
    return False


# Matches the adversarial acceptable-status assertion emitted by the Jinja
# template: "Adversarial test expected ANY of [200, 400, 401] (attack
# neutralized), got 422 ...". Group 1 is the actual status.
_ADV_STATUS_LIST_RE = re.compile(
    r"Adversarial test expected ANY of \[[^\]]*\].*?got\s+(\d{3})\b",
    re.DOTALL,
)


def _rejection_says_neutralized(tc: TestCase, detail: str) -> Optional[int]:
    """Status-misexpectation guard — returns the actual status when the
    failed assertion was the adversarial acceptable-status check AND the app
    actually REJECTED the request with a 4xx that is not an exploit-success
    code for this route.

    Background (r_e533db86): the Generator's acceptable-status lists omitted
    422 — FastAPI's standard Pydantic rejection — so registration tests
    where the app correctly rejected a weak password with 422 flipped to
    "vulnerable" (5/5 of the run's vulnerable verdicts; the Healer
    simultaneously called them test defects). A 4xx rejection with no body
    leak is evidence the attack was NEUTRALIZED; only the test's status
    list was incomplete.
    """
    m = _ADV_STATUS_LIST_RE.search(detail or "")
    if not m:
        return None
    try:
        actual = int(m.group(1))
    except ValueError:
        return None
    if 400 <= actual <= 499 and not _is_exploit_success_status(tc, actual):
        return actual
    return None


def _classify_adversarial_failure(
    tc: TestCase,
    detail: str,
    binding: Optional["SurfaceBinding"] = None,
) -> Tuple[str, List[str]]:
    """Return (verdict, evidence) for an adversarial test pytest-fail.

    Verdict is one of ``"vulnerable"``, ``"resilient"``, ``"inconclusive"``.

    Decision order:

      1. Run the attestation cascade — that's the AUTHORITY when a stamp
         exists. (The cascade NEVER uses needles.)
      2. Run independent body-evidence checks (tier B1–B3) — these can
         promote ``inconclusive`` to ``vulnerable`` and override
         ``resilient`` if the body actually leaks.
      3. Status-misexpectation guard (defense_confirming only): a cascade
         "vulnerable" where the app actually rejected the request with a
         non-exploit 4xx and nothing leaked is a test-authoring gap, not a
         vulnerability → ``"resilient"`` with explicit evidence.
      4. If the cascade returned ``"resilient"`` and no body evidence
         fired, keep ``"resilient"``.
      5. If the cascade returned ``"inconclusive"`` and no body evidence
         fired, the result is honestly UNCLASSIFIED → ``"inconclusive"``.

    Net effect: explicit stamps win unless the response shows a hard
    exploit signal — or hard rejection evidence proving the attack never
    got through.
    """
    v_cascade, ev_cascade = adversarial_verdict_on_fail(tc, detail, binding)
    body_says_vuln = _body_evidence_says_vulnerable(tc, detail)

    if body_says_vuln:
        # Body evidence wins in every branch — when the body says the app
        # leaked, we trust the body. The "body-evidence" marker is load-
        # bearing: the Healer↔verdict reconciliation in executor.py will
        # NOT downgrade a vulnerable verdict that carries it (hard exploit
        # evidence beats the Healer's LLM opinion).
        if v_cascade == "vulnerable":
            return "vulnerable", ev_cascade + [
                "body-evidence: forbidden token / exploit-success status hit"
            ]
        ev = ev_cascade + ["body-evidence override: forbidden token / exploit-success status hit"]
        return "vulnerable", ev

    if v_cascade == "vulnerable":
        # Misexpectation guard — scoped to defense_confirming, where a
        # pytest fail is otherwise read as "defense did not hold". Style-2
        # missing_control probes are exempt: their fail condition (expected
        # enforcement status never fired) is meaningful regardless of how
        # the request was rejected.
        if infer_attestation_mode(tc, binding) == "defense_confirming":
            rejected = _rejection_says_neutralized(tc, detail)
            if rejected is not None:
                return (
                    "resilient",
                    [
                        f"attestation_mode=defense_confirming — request REJECTED "
                        f"with {rejected} (outside the test's acceptable-status "
                        f"list) and no forbidden content leaked → attack "
                        f"neutralized; status-list misexpectation, not a "
                        f"vulnerability"
                    ],
                )
        return "vulnerable", ev_cascade
    if v_cascade == "resilient":
        return "resilient", ev_cascade
    # UNCLASSIFIED with no body evidence → honest inconclusive.
    return "inconclusive", ev_cascade


# Injection / content OWASP class: a verdict about *response content* (an
# injected payload surviving, a forbidden fragment appearing) can only be
# substantiated by the body — never by a bare success status.
_CONTENT_CLASS_RE = re.compile(r"\bA03\b|injection|xss|sqli|\bhtml\b", re.IGNORECASE)


def _is_content_class_probe(tc: TestCase) -> bool:
    """True when the adversarial claim is about *response content* (payload
    survival / a forbidden fragment appearing) rather than a behavioural
    signal (rate-limit throttle, IDOR status). Content claims cannot be
    judged from the HTTP status alone — a 2xx is returned whether or not the
    payload was sanitized."""
    if tc.forbidden_response_content:
        return True
    tag = f"{tc.owasp_category or ''} {tc.exploit_target or ''}"
    return bool(_CONTENT_CLASS_RE.search(tag))


def _classify_adversarial_pass(
    tc: TestCase,
    detail: str,
    binding: Optional["SurfaceBinding"] = None,
) -> Tuple[str, List[str]]:
    """Return (verdict, evidence) for an adversarial test pytest-*pass*.

    Wraps the pure cascade with a body-evidence gate mirroring
    ``_classify_adversarial_failure``. On a pass the cascade returns
    "vulnerable" only for a missing_control *style-1* test (expects the
    unprotected status). For a CONTENT-class probe (XSS / SQLi / HTML /
    forbidden-fragment) a bare success-status pass proves nothing — the app
    returns the same 2xx whether or not the payload was sanitized. Without
    positive body evidence that the payload actually survived, the gap is
    UNCONFIRMED, so the honest verdict is ``inconclusive`` (counted in the
    unclassified bucket, excluded from resilience %, surfaced amber) rather
    than a confident "vulnerable".

    Behavioural probes (rate-limit / brute-force / IDOR) — whose status IS
    the evidence — are untouched. This gate only ever *withholds* a
    vulnerable verdict; it can never produce "resilient", so it carries no
    false-green risk.
    """
    v_cascade, ev_cascade = adversarial_verdict_on_pass(tc, binding)
    if v_cascade != "vulnerable":
        return v_cascade, ev_cascade
    if _is_content_class_probe(tc) and not _body_evidence_says_vulnerable(tc, detail):
        return (
            "inconclusive",
            ev_cascade
            + [
                "pass-path evidence gate: content-class missing_control probe "
                "passed on a success status with no body evidence the payload "
                "survived — gap unconfirmed; verdict withheld as inconclusive "
                "rather than asserted vulnerable"
            ],
        )
    return v_cascade, ev_cascade


# --------------------------------------------------------------------------- #
# Layer A — Classifier tier 0: off-target guard.                              #
# --------------------------------------------------------------------------- #

_ACTION_PATH_RE = re.compile(
    r"(?:GET|POST|PATCH|PUT|DELETE|HEAD|OPTIONS)\s+(/[^\s,;]+)",
    re.IGNORECASE,
)


def _tier0_path_probes(tc: TestCase) -> List[str]:
    """Paths to check against a requirement binding (workflow steps + action)."""
    from .generator import _probe_workflow_path

    probes: List[str] = []
    for step in tc.workflow_steps or []:
        probed = _probe_workflow_path(step.path)
        if probed not in probes:
            probes.append(probed)
    is_transition = (tc.test_category or "").lower() == "state_transition" or (
        (tc.test_technique or "").lower() == "state_transition"
    )
    if is_transition:
        for match in _ACTION_PATH_RE.finditer(tc.action or ""):
            probed = _probe_workflow_path(match.group(1).strip())
            if probed not in probes:
                probes.append(probed)
    return probes


def _tier0_uses_workflow_gate(tc: TestCase) -> bool:
    """Workflow-style tests: multi-step array or state_transition label."""
    return (
        len(tc.workflow_steps or []) >= 2
        or (tc.test_category or "").lower() == "state_transition"
        or (tc.test_technique or "").lower() == "state_transition"
    )


def _tier0_off_target(
    tc: TestCase,
    surface_map: Optional[Dict[str, "SurfaceBinding"]],
) -> Optional[Tuple[str, List[str]]]:
    """Return (verdict, evidence) if the test should be marked off_target;
    otherwise None and the classifier continues to tier 1.

    The check has two arms:

      Arm A — binding state is not BACKEND_API. Anything we observed via
      pytest is semantically null — the SurfaceMap says the harness can't
      honestly test this requirement.

      Arm B — binding IS BACKEND_API but the test's bound_path (or, as a
      fallback, the path inferred from action) does not match any bound
      endpoint. Multi-step workflows are exempt when *any* workflow step
      matches this requirement's endpoints (POST setup + PATCH assert is OK).
      This catches Rule 11 escapes and Compiler bugs that re-routed a mutation.

    Both functional and adversarial tests are gated — a wrong-path
    functional failure should NOT trigger the Healer, which is what
    happens without the tier-0 functional branch.
    """
    if not surface_map or not tc.covered_requirement_id:
        return None
    binding = surface_map.get(tc.covered_requirement_id)
    if binding is None:
        return None

    if binding.state in ("CLIENT_SIDE_ONLY", "NOT_IMPLEMENTED", "NEEDS_CLARIFICATION", "FRONTEND_ONLY"):
        return ("off_target", [f"binding state {binding.state} — API test not valid"])

    if binding.state == "BACKEND_API":
        bound_paths = [ep.path for ep in binding.backend_endpoints]
        if _tier0_uses_workflow_gate(tc) and bound_paths:
            probes = _tier0_path_probes(tc)
            if any(_paths_match_any(probe, bound_paths) for probe in probes):
                return None
            if probes or len(tc.workflow_steps or []) >= 2:
                steps_repr = [f"{s.method} {s.path}" for s in (tc.workflow_steps or [])]
                return (
                    "off_target",
                    [
                        f"no path matches binding endpoints {bound_paths}; "
                        f"workflow_steps={steps_repr}; action={tc.action!r}"
                    ],
                )

        # Single-shot: prefer Generator-stamped bound_path; fall back to inference.
        bound = tc.bound_path
        if not bound:
            from .security_compiler import _method_path_from_action
            _m, bound, _err = _method_path_from_action(
                tc.action or "", title=tc.title or "", input_data=tc.input_data,
            )
        if bound and bound_paths and not _paths_match_any(bound, bound_paths):
            return (
                "off_target",
                [f"bound_path={bound} not in binding endpoints {bound_paths}"],
            )

    return None


def _parse_junit_cases(junit_path: Path) -> Dict[str, Tuple[str, str]]:
    """Map pytest function name (`test_tc_req_001_01`) → (status, detail).

    status is passed | failed | error | skipped.
    """

    out: Dict[str, Tuple[str, str]] = {}
    if not junit_path.is_file():
        return out
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError:
        return out
    root = tree.getroot()
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        failure = case.find("failure")
        err_el = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            msg = failure.get("message", "") or ""
            text = (failure.text or "")[:4000]
            out[name] = ("failed", f"{msg}\n{text}".strip())
        elif err_el is not None:
            msg = err_el.get("message", "") or ""
            text = (err_el.text or "")[:4000]
            out[name] = ("error", f"{msg}\n{text}".strip())
        elif skipped is not None:
            detail = skipped.get("message", "") or (skipped.text or "") or "skipped"
            out[name] = ("skipped", str(detail)[:2000])
        else:
            out[name] = ("passed", "")
    return out


def run_pytest_generated_file(
    test_suite: List[TestCase],
    py_path: Path,
    *,
    cwd: Path | None = None,
    timeout_sec: int | None = None,
    surface_map: Optional[Dict[str, SurfaceBinding]] = None,
) -> Tuple[List[ExecutionLog], int, str, str]:
    """Run ``pytest <file>`` with JUnit XML, return logs aligned to ``test_suite`` order.

    Layer A: `surface_map` enables the tier-0 off-target classifier branch.
    When supplied, tests whose covered_requirement_id binding is not
    BACKEND_API — OR whose bound_path is outside the binding's endpoints —
    are stamped verdict='off_target' regardless of pytest outcome. Off-
    target tests do not contribute to posture math (denominator excludes
    them) and do not trigger the Healer.
    """

    work_cwd = cwd or BACKEND_ROOT
    if timeout_sec is None:
        timeout_sec = int(os.getenv("SENTINEL_PYTEST_TIMEOUT_SEC", "900"))

    tmp_dir = Path(tempfile.mkdtemp(prefix="sentinel_junit_"))
    junit_path = tmp_dir / "junit.xml"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(py_path.resolve()),
        "-q",
        "--tb=short",
        f"--junitxml={junit_path}",
        "-o",
        "junit_family=xunit2",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_cwd.resolve()),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=_subprocess_env(),
        )
    except subprocess.TimeoutExpired as exc:
        # A hung target API or pathological test would otherwise propagate
        # TimeoutExpired out of executor_node and crash the LangGraph run.
        # Convert into one error-status ExecutionLog per test so needs_healing
        # sees the failure and routes "heal" once (bounded by max_heal_attempts)
        # instead of the whole graph aborting.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        stdout_part = (exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
        stderr_part = (exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
        timeout_msg = (
            f"pytest subprocess exceeded {timeout_sec}s timeout — target API hung "
            f"or test is pathological. Killed and converted to per-test error logs."
        )
        timeout_logs: List[ExecutionLog] = [
            ExecutionLog(
                test_id=tc.test_id,
                status="error",
                is_adversarial=tc.is_adversarial,
                passed=False if not tc.is_adversarial else None,
                is_vulnerable=None,
                resilient=None,
                exploit_target=tc.exploit_target,
                verdict="n/a",
                bound_surface_state=tc.bound_surface_state,
                stderr=timeout_msg,
            )
            for tc in test_suite
        ]
        return timeout_logs, -1, stdout_part, (stderr_part + "\n" + timeout_msg).strip()

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    cases = _parse_junit_cases(junit_path)

    logs: List[ExecutionLog] = []
    for tc in test_suite:
        # NEW-2: propagate exploit_target onto every log so security_posture's
        # by_exploit_target breakdown shows per-OWASP buckets instead of one
        # giant "unknown" bucket. Demo-artifact bug was exactly this.
        et = tc.exploit_target
        func_name = "test_" + slug_from_test_id(tc.test_id)

        # Layer A — Classifier tier 0: off-target guard.
        # Fires BEFORE looking at pytest outcome. If the binding says the
        # test's REQ isn't a backend surface, OR the test's bound_path is
        # outside the binding's endpoints, the verdict is off_target and
        # nothing the runner observed is admissible evidence.
        tier0 = _tier0_off_target(tc, surface_map)
        if tier0 is not None:
            verdict, evidence = tier0
            is_vuln, is_resi = _legacy_fields_from_verdict(verdict)
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="off_target",
                    is_adversarial=tc.is_adversarial,
                    is_vulnerable=is_vuln,
                    resilient=is_resi,
                    exploit_target=et,
                    verdict=verdict,
                    verdict_confidence="high",
                    verdict_evidence=evidence,
                    bound_surface_state=tc.bound_surface_state,
                    stderr="[tier-0 off-target] " + "; ".join(evidence),
                )
            )
            continue

        if func_name not in cases:
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="error",
                    is_adversarial=tc.is_adversarial,
                    passed=False if not tc.is_adversarial else None,
                    is_vulnerable=None,
                    resilient=None,
                    exploit_target=et,
                    verdict="n/a",
                    bound_surface_state=tc.bound_surface_state,
                    stderr=(
                        f"No JUnit entry for `{func_name}` "
                        f"(emit truncated, collect error, or slug drift). "
                        f"pytest exit={proc.returncode}"
                    ),
                )
            )
            continue

        st, detail = cases[func_name]
        # Look up binding once per test — used by the attestation cascade
        # for both pass and fail paths. None when surface_map is empty
        # (back-compat / Resolver-disabled runs) or the REQ wasn't bound.
        binding = (
            surface_map.get(tc.covered_requirement_id)
            if surface_map and tc.covered_requirement_id
            else None
        )

        if st == "passed":
            if tc.is_adversarial:
                stamp_attestation_mode(tc, binding)
                v, evidence = _classify_adversarial_pass(tc, detail or "", binding)
                isv, isr = _legacy_fields_from_verdict(v)
                # confidence: high when an explicit stamp drove the verdict,
                # low when we landed on inconclusive (UNCLASSIFIED).
                confidence = "low" if v == "inconclusive" else "high"
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="passed",
                        is_adversarial=True,
                        is_vulnerable=isv,
                        resilient=isr,
                        exploit_target=et,
                        verdict=v,
                        verdict_confidence=confidence,
                        verdict_evidence=evidence,
                        bound_surface_state=tc.bound_surface_state,
                        stdout=detail[:2000] if detail else None,
                    )
                )
            else:
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="passed",
                        is_adversarial=False,
                        passed=True,
                        exploit_target=et,
                        verdict="n/a",
                        bound_surface_state=tc.bound_surface_state,
                        stdout=detail[:2000] if detail else None,
                    )
                )
        elif st == "skipped":
            # A skipped test never observed the attacker class (or for functional
            # tests: never observed the behaviour under test). It MUST NOT be
            # rolled into resilient/passed counts — that would manufacture
            # phantom security posture from tests that did not run.
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="skipped",
                    is_adversarial=tc.is_adversarial,
                    passed=None,
                    is_vulnerable=None,
                    resilient=None,
                    exploit_target=et,
                    verdict="n/a",
                    bound_surface_state=tc.bound_surface_state,
                    stderr=("pytest skipped: " + detail)[:4000],
                )
            )
        elif st == "failed":
            if tc.is_adversarial:
                stamp_attestation_mode(tc, binding)
                v, evidence = _classify_adversarial_failure(tc, detail or "", binding)
                isv, isr = _legacy_fields_from_verdict(v)
                # Map verdict → log_status:
                #   vulnerable  → "failed" (real test failure surfaces in the
                #                 pytest counter, drives Healer routing)
                #   resilient   → "passed" (defense held; pytest "fail" was the
                #                 desired outcome — the attack was repelled)
                #   inconclusive → "failed" (the test ran and pytest reported
                #                 failed; we honestly don't know if the app is
                #                 vulnerable or just behaved unexpectedly)
                log_status = "passed" if v == "resilient" else "failed"
                confidence = (
                    "low" if v == "inconclusive"
                    else "medium" if not binding or not binding.attestation_mode
                    else "high"
                )
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status=log_status,
                        is_adversarial=True,
                        is_vulnerable=isv,
                        resilient=isr,
                        exploit_target=et,
                        verdict=v,
                        verdict_confidence=confidence,
                        verdict_evidence=evidence,
                        bound_surface_state=tc.bound_surface_state,
                        stderr=detail[:8000],
                    )
                )
            else:
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="failed",
                        is_adversarial=False,
                        passed=False,
                        exploit_target=et,
                        verdict="n/a",
                        bound_surface_state=tc.bound_surface_state,
                        stderr=detail[:8000],
                    )
                )
        else:  # error
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="error",
                    is_adversarial=tc.is_adversarial,
                    passed=False if not tc.is_adversarial else None,
                    is_vulnerable=None,
                    resilient=None,
                    exploit_target=et,
                    verdict="n/a",
                    bound_surface_state=tc.bound_surface_state,
                    stderr=detail[:8000],
                )
            )

    shutil.rmtree(tmp_dir, ignore_errors=True)

    return logs, proc.returncode, stdout, stderr
