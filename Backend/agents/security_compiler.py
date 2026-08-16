"""Agent C — Security + Compiler (OWASP payloads → adversarial tests + pytest).

Expands the functional `test_suite` from the Generator with adversarial
variants using the OWASP payload library (scoped to Critic `security_risks`).

Materializes a **single combined** `test_sentinel_api_generated.py` per run under
`workspace/runs/run_<UTC-timestamp>_utc/`, targeting a live API via **httpx**
and **SENTINEL_BASE_URL** (see `.env.example`). Templates live in
`agents/templates/pytest_api.jinja2` (Jinja2, autoescape off — Python source).

PRE_CODE mode:
  Skips all payload mutation and pytest materialization. For each SecurityRisk
  identified by the Critic, calls the LLM to produce one or more
  SecurityChecklistItems — developer-facing security instructions the team must
  satisfy before writing any code. Results stored in state.security_checklist.
"""

from __future__ import annotations

import copy
import json
import logging
import py_compile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader
from langchain_core.prompts import ChatPromptTemplate

from config import get_settings
from state import ProjectState, SecurityRisk, SecurityChecklistItem, SurfaceBinding, TestCase
from utils import (
    LLMInvocationError,
    Payload,
    get_local_llm,
    get_payloads,
    invoke_with_retry,
    parse_llm_json,
)
from utils.boundaries import RESILIENCE_SIGNATURES, VULNERABILITY_SIGNATURES

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


# ---------------------------------------------------------------------------
# PRE_CODE prompts
# ---------------------------------------------------------------------------

SECURITY_CHECKLIST_SYSTEM_PROMPT = """You are a senior application-security engineer.
You will be given a user story requirement and a specific OWASP security risk that a
security critic identified for that story.

Your job is to produce a list of concrete, story-specific developer security instructions
that the engineering team must implement BEFORE writing any code.

Rules:
- Each instruction must be specific to this story and this risk — no generic advice.
- Each instruction must be independently testable.
- Output ONLY a JSON array. No preamble, no markdown fences, no commentary.

Each element of the array must have exactly these keys:
  "owasp_id"           : the OWASP identifier (e.g. "A01:2021")
  "requirement_id"     : the requirement id provided
  "instruction"        : a short, imperative developer instruction (≤ 25 words)
  "rationale"          : why this matters specifically for this story (1–2 sentences)
  "definition_of_done" : a testable condition starting with "Verified when..."
"""

SECURITY_CHECKLIST_USER_PROMPT = """Requirement ID: {requirement_id}
Requirement statement: {statement}
Acceptance criteria: {acceptance_criteria}

OWASP Risk identified by security critic:
  owasp_id  : {owasp_id}
  title     : {title}
  rationale : {risk_rationale}
  affected_requirements: {affected_requirements}

Produce the JSON array of SecurityChecklistItems for this risk."""


# ---------------------------------------------------------------------------
# PRE_CODE helper
# ---------------------------------------------------------------------------

def _call_llm_for_checklist_items(
    llm,
    risk: SecurityRisk,
    requirement_id: str,
    statement: str,
    acceptance_criteria: str,
) -> List[SecurityChecklistItem]:
    """Call LLM for one risk/requirement pair, return SecurityChecklistItem list."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SECURITY_CHECKLIST_SYSTEM_PROMPT),
            ("user", SECURITY_CHECKLIST_USER_PROMPT),
        ]
    )
    chain = prompt | llm
    response = invoke_with_retry(
        chain.invoke,
        {
            "requirement_id": requirement_id,
            "statement": statement,
            "acceptance_criteria": acceptance_criteria,
            "owasp_id": risk.owasp_id,
            "title": risk.title,
            "risk_rationale": risk.rationale,
            "affected_requirements": ", ".join(
                risk.affected_requirements or [requirement_id]
            ),
        },
    )

    payload = parse_llm_json(response.content)

    # System prompt asks for a bare JSON array; handle both shapes defensively:
    #   [ {...}, {...} ]        ← direct array (expected)
    #   { "items": [...] }     ← wrapped object (occasional LLM drift)
    if isinstance(payload, list):
        items_data = payload
    elif isinstance(payload, dict):
        for key in ("items", "checklist", "security_checklist", "results"):
            if isinstance(payload.get(key), list):
                items_data = payload[key]
                break
        else:
            items_data = next(
                (v for v in payload.values() if isinstance(v, list)), []
            )
    else:
        items_data = []

    checklist_items: List[SecurityChecklistItem] = []
    for item in items_data:
        try:
            checklist_items.append(SecurityChecklistItem(**item))
        except Exception:
            continue

    return checklist_items


# ---------------------------------------------------------------------------
# Unchanged POST_CODE helpers
# ---------------------------------------------------------------------------

def _workspace_root() -> Path:
    raw = (get_settings().sentinel_workspace_root or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_BACKEND_ROOT / "workspace").resolve()


def _max_tests_per_file() -> int:
    raw = get_settings().sentinel_compiler_max_tests_per_file
    try:
        return max(1, min(500, int(raw)))
    except ValueError:
        return 80


def _max_adversarial() -> int:
    """Cap adversarial rows before extend (matches .env.example SENTINEL_COMPILER_MAX_ADVERSARIAL)."""

    raw = get_settings().sentinel_compiler_max_adversarial
    try:
        return max(1, min(10_000, int(raw)))
    except ValueError:
        return 200


# Maps Critic OWASP short id → RESILIENCE_SIGNATURES / VULNERABILITY_SIGNATURES key in utils.boundaries.
_OWASP_TO_RESILIENCE_KEY: Dict[str, str] = {
    "A01": "A01_ACCESS_CONTROL",
    "A02": "A02_CRYPTO_FAILURE",
    "A03": "A03_INJECTION",
    "A04": "A04_INSECURE_DESIGN",
    "A05": "A05_SECURITY_MISCONFIGURATION",
    "A07": "A07_AUTH_FAILURE",
    "A08": "A08_INTEGRITY_FAILURE",
    "A10": "A10_SSRF",
}


def slug_from_test_id(test_id: str) -> str:
    """Public alias for junit ↔ TestCase mapping (executor / pytest runner)."""

    return _slug_from_test_id(test_id)


def _slug_from_test_id(test_id: str) -> str:
    s = re.sub(r"[^0-9A-Za-z_]+", "_", test_id)
    s = re.sub(r"_+", "_", s).strip("_").lower()
    if s and s[0].isdigit():
        s = "t_" + s
    return s[:120] if s else "unnamed"


# --------------------------------------------------------------------------- #
# P1-8 (Cursor) — multi-source METHOD/path inference                          #
# --------------------------------------------------------------------------- #
#
# The Generator's Rule 3a *instructs* the LLM to start `action` with
# "<METHOD> <path>", but the LLM follows that ~71% of the time. The other
# 29% emit natural-language phrases ("Attempt to log in with a 1000-char
# username") which the strict regex rejects, producing pytest.skip() at
# test entry — observed in exec-demo-login-post_code-20260528_195120 where
# 9 of 31 tests skipped for "Could not infer HTTP method and path".
#
# Four tiers of inference, first confident hit wins:
#   1. METHOD-path regex on `action`         (the documented contract)
#   2. METHOD-path regex on `title`          (rescue when route lives in the title)
#   3. Bare path in action+title, default POST  (path mentioned, no verb)
#   4. Heuristic from `input_data` shape +   (email+password → /login or
#      title/action keywords                   /register based on intent)
#
# If all four fail we emit a skip_reason that NAMES the sources we examined.
# Tier 4 only fires for shapes that unambiguously match a known target route
# (currently the Smart Task Manager auth endpoints); it does NOT invent
# routes the target doesn't expose.

_METHOD_PATH_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b\s*[^\n/]*?(/[A-Za-z0-9_\-./]+)",
    re.IGNORECASE | re.DOTALL,
)
# FastAPI path templates in prose actions (observed: "GET /tasks/{task_id}").
_METHOD_PATH_TEMPLATE_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b\s*.*?(/[A-Za-z0-9_\-./]*\{[a-zA-Z_][a-zA-Z0-9_]*\})",
    re.IGNORECASE | re.DOTALL,
)
# Literal UUID task ids in AC text (e.g. GET /tasks/550e8400-e29b-41d4-a716-446655440000).
_TASK_UUID_PATH_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b\s*.*?"
    r"(/tasks/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
    re.IGNORECASE | re.DOTALL,
)
_BARE_PATH_RE = re.compile(r"(/[A-Za-z][A-Za-z0-9_/\-]{0,200})")

# Title-keyword routing for known target endpoints. Conservative: only routes
# the current target (Smart Task Manager) actually exposes.
_HEURISTIC_ROUTES = {
    "login":    ("POST", "/login"),
    "register": ("POST", "/register"),
    "logout":   ("POST", "/logout"),
    "tasks":    ("GET",  "/tasks/"),
    "task":     ("GET",  "/tasks/"),
}


def _try_method_path_template(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Tier 0: METHOD + FastAPI template path (e.g. GET /tasks/{task_id})."""
    if not text or "{" not in text:
        return None, None
    m = _METHOD_PATH_TEMPLATE_RE.search(text)
    if not m:
        return None, None
    path = m.group(2).strip()
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    return m.group(1).upper(), path


def _try_method_path_task_uuid(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Tier 0b: METHOD + /tasks/<uuid> literal (matches binding template at Rule 11)."""
    if not text:
        return None, None
    m = _TASK_UUID_PATH_RE.search(text)
    if not m:
        return None, None
    return m.group(1).upper(), m.group(2).strip()


def _try_method_path_regex(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Tier 1/2: strict METHOD + path regex. Reject paths with `{...}` placeholders."""
    if not text:
        return None, None
    m = _METHOD_PATH_RE.search(text)
    if not m:
        return None, None
    path = m.group(2).strip()
    if "{" in path or "}" in path:
        return None, None
    if not path.startswith("/"):
        path = "/" + path.lstrip("/")
    return m.group(1).upper(), path


def _try_bare_path(text: str) -> Optional[str]:
    """Tier 3: bare-path mentioned (e.g. `/login`) without a verb. Default POST."""
    if not text:
        return None
    m = _BARE_PATH_RE.search(text)
    if not m:
        return None
    path = m.group(1)
    if "{" in path or "}" in path:
        return None
    return path


def _heuristic_from_input_and_title(
    input_data: Any, title: str, action: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Tier 4: infer from input_data shape + title/action keywords.

    Only fires when the input_data shape unambiguously matches a known route
    AND a title/action keyword narrows the intent. Returns (None, None)
    otherwise — refuses to invent.
    """
    if not isinstance(input_data, dict):
        return None, None
    keys = {k.lower() for k in input_data.keys()}
    combined = f"{title or ''} {action or ''}".lower()

    # email+password (or username+password) is the auth-route shape.
    # `register / sign up / create account` keyword → /register; else /login
    # (login is the more common test target on this fixture).
    if {"email", "password"}.issubset(keys) or {"username", "password"}.issubset(keys):
        if any(kw in combined for kw in
               ("register", "sign up", "signup", "create account", "new account")):
            return "POST", "/register"
        return "POST", "/login"

    # Single-field email → register partial flow (Smart Task Manager only).
    if keys == {"email"}:
        return "POST", "/register"

    # task_id in payload → resource-scoped /tasks/{id} (not list GET /tasks/).
    tid = input_data.get("task_id") or input_data.get("id")
    if isinstance(tid, str) and tid.strip():
        literal = f"/tasks/{tid.strip()}"
        if "delete" in combined:
            return "DELETE", literal
        if "patch" in combined or "update" in combined:
            return "PATCH", literal
        if "post" in combined and "task" in combined:
            return "POST", "/tasks/"
        return "GET", literal

    # Prose mentions {task_id} or per-task routes — avoid collapsing to GET /tasks/.
    if "{task_id}" in combined or "task_id}" in combined:
        if "delete" in combined:
            return "DELETE", "/tasks/{task_id}"
        if "patch" in combined or "update" in combined:
            return "PATCH", "/tasks/{task_id}"
        return "GET", "/tasks/{task_id}"

    # Title-keyword routing as last gasp (list/create only — not when AC names an id).
    if not ("{task_id}" in combined or re.search(r"/tasks/[0-9a-fA-F-]{36}", combined)):
        for keyword, (method, path) in _HEURISTIC_ROUTES.items():
            if keyword in combined:
                return method, path

    return None, None


def _method_path_from_action(
    action: str,
    *,
    title: str = "",
    input_data: Any = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Four-tier METHOD/path inference. Backward-compatible single-arg form
    still works (tiers 1 + 3 only) — callers using kwargs get all four tiers.
    """
    # Tier 0 — FastAPI template paths ({task_id}) before regex truncates at `{`
    meth, path = _try_method_path_template(action)
    if meth and path:
        return meth, path, None
    meth, path = _try_method_path_template(title)
    if meth and path:
        return meth, path, None

    meth, path = _try_method_path_task_uuid(action)
    if meth and path:
        return meth, path, None
    meth, path = _try_method_path_task_uuid(title)
    if meth and path:
        return meth, path, None

    # Tier 1 — strict regex on action (original behaviour)
    meth, path = _try_method_path_regex(action)
    if meth and path:
        return meth, path, None

    # Tier 2 — strict regex on title
    meth, path = _try_method_path_regex(title)
    if meth and path:
        return meth, path, None

    # Tier 3 — bare path on combined text, default POST
    bare = _try_bare_path(f"{action or ''} {title or ''}")
    if bare:
        return "POST", bare, None

    # Tier 4 — input_data shape + intent keywords
    meth, path = _heuristic_from_input_and_title(input_data, title, action or "")
    if meth and path:
        return meth, path, None

    # All four exhausted — name the inputs we examined.
    return None, None, (
        "Could not infer HTTP method and path from "
        f"action={(action or '')[:120]!r}, "
        f"title={(title or '')[:120]!r}, "
        f"input_data keys={list(input_data.keys()) if isinstance(input_data, dict) else type(input_data).__name__}"
    )


def _infer_use_auth(tc: TestCase) -> bool:
    """Attach Bearer token only when the test is not explicitly unauthenticated."""

    action = (tc.action or "").lower()
    title = (tc.title or "").lower()
    if tc.expected_status_code == 401:
        return False
    if "unauthenticated" in action or "unauthenticated" in title:
        return False
    if "without" in action and any(
        x in action for x in ("bearer", "token", "jwt", "authorization")
    ):
        return False
    if "no bearer" in action or "no token" in action:
        return False
    return True


_UUID_IN_PATH_RE = re.compile(
    r"/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_TEMPLATE_PARAM_IN_PATH_RE = re.compile(r"/\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def _is_resource_id_route(path: str) -> bool:
    """True when the request targets a single resource by id (not a list route).

    404 on unknown/forbidden ids is a valid neutralization for injection/IDOR
    probes — distinct from POST /login or /register body validation.
    """
    if not path:
        return False
    if _TEMPLATE_PARAM_IN_PATH_RE.search(path):
        return True
    if _UUID_IN_PATH_RE.search(path):
        return True
    return False


def _request_path_for_adversarial(tc: TestCase) -> str:
    """Best-effort path used to decide 404-as-resilient (bound_path wins)."""
    if tc.bound_path:
        return tc.bound_path
    meth, path, _ = _method_path_from_action(
        tc.action or "",
        title=tc.title or "",
        input_data=tc.input_data,
    )
    return path or ""


def _acceptable_status_codes_for_adversarial(tc: TestCase) -> List[int]:
    """Resolve the FULL list of HTTP status codes that count as a SUCCESSFUL
    NEUTRALIZATION for an adversarial test.

    Background: `_mutate` currently sets `tc.expected_status_code` to a single
    int — `RESILIENCE_SIGNATURES[key]["http_status"][0]` — which forces the
    generated pytest to assert `status == <one code>`. The target app may
    correctly neutralize an A03 payload with ANY of (400, 401, 422)
    depending on which route the payload hits:
        /login + bad creds → 401 (attack literal-stringed; auth lookup failed)
        /register + bad email → 422 (Pydantic EmailStr rejected)
        custom-validator app → 400 (explicit HTTPException)
    Asserting `== 400` flips the resilient 401/422 responses to "vulnerable"
    in the posture report. We observed 26 false-positive vulnerabilities
    from exactly this gap (exec-demo-login-post_code-20260528_163728).

    Returns the FULL list when the OWASP id maps to a known resilience
    signature; otherwise returns `[tc.expected_status_code]` (single-code
    fallback). Functional (non-adversarial) tests are NOT remapped — they
    have specific expected outcomes the caller must preserve.
    """
    if not tc.is_adversarial or not tc.owasp_category:
        return [tc.expected_status_code] if tc.expected_status_code is not None else []

    short = tc.owasp_category.split(":", 1)[0].strip().upper()
    key = _OWASP_TO_RESILIENCE_KEY.get(short)
    if not key:
        return [tc.expected_status_code] if tc.expected_status_code is not None else []

    codes = list(RESILIENCE_SIGNATURES.get(key, {}).get("http_status") or [])
    if not codes:
        codes = [tc.expected_status_code] if tc.expected_status_code is not None else []
    codes = [int(c) for c in codes]
    # P1 — id-route adversarial probes: 404 means "no such row / not yours" (safe).
    req_path = _request_path_for_adversarial(tc)
    if _is_resource_id_route(req_path) and 404 not in codes:
        codes = sorted(set(codes) | {404})
    # Pydantic/FastAPI neutralizes malformed input with 422 — every signature
    # list must accept it as a rejection. Without this, correct validation
    # flips false-vulnerable (observed r_e533db86: 5/5 "vulnerable" verdicts
    # were 422 rejections the test's list didn't include). Style-2
    # missing_control probes keep their strict list — their pass condition
    # IS the specific enforcement status (429/423), not any rejection.
    if tc.attestation_mode != "missing_control" and 422 not in codes:
        codes = sorted(set(codes) | {422})
    return codes


def _payload_python_literal(input_data: Any) -> str:
    """Build a safe `repr(...)` for embedding as `payload = ...` in generated tests."""

    if isinstance(input_data, dict):
        clean = {k: v for k, v in input_data.items() if k != "_repeat"}
        try:
            normalized: Any = json.loads(json.dumps(clean, default=str))
        except (TypeError, ValueError):
            normalized = clean
        return repr(normalized)
    if isinstance(input_data, list):
        try:
            normalized = json.loads(json.dumps(input_data, default=str))
        except (TypeError, ValueError):
            normalized = input_data
        return repr(normalized)
    if input_data is None:
        return "{}"
    # Scalar / unexpected shapes: never silently emit `{}` (breaks GET params / hides intent).
    return repr({"_scalar": str(input_data)})


def _materialize_pytest_workspace(state: ProjectState) -> None:
    """Write Jinja-rendered pytest module and record path only after py_compile passes."""

    tests_all: List[TestCase] = list(state.test_suite)
    if not tests_all:
        return

    cap = _max_tests_per_file()
    truncated = False
    if len(tests_all) > cap:
        dropped = len(tests_all) - cap
        tests_all = tests_all[:cap]
        truncated = True
        state.metadata["security_compiler_tests_truncated_to"] = cap
        state.metadata["security_compiler_tests_dropped_by_cap"] = dropped
        # CRITICAL: keep state.test_suite IN SYNC with what we actually write
        # to the pytest file. Previously the file was capped to `cap` tests but
        # state.test_suite kept all N — so the executor expected N, the runner
        # found only `cap` JUnit entries, and the (N-cap) overflow tests were
        # logged as ERRORED ("No JUnit entry … emit truncated"). Those ghost
        # errors then drove garbage Healer patches (observed: 22 ghost errors
        # + ~16 spurious patches on lifecycle). Drop the overflow from the
        # suite so suite, file, and run_logs all describe the same tests.
        state.test_suite = list(tests_all)

    root = _workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    run_dir = runs_dir / f"run_{stamp}_utc"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    used_slugs: set[str] = set()
    for tc in tests_all:
        # Layer A — prefer Generator-stamped bound_method/bound_path over
        # the 4-tier inference. Generator validation already proved these
        # match the SurfaceBinding; using them removes the chance of the
        # inference disagreeing with the binding (which would re-introduce
        # the "Compiler sends to /tasks but binding said /tasks/{task_id}"
        # class of error). Inference only fires when no binding was stamped
        # (back-compat / pre-Layer-A tests).
        skip_reason: Optional[str] = None
        if tc.bound_method and tc.bound_path:
            meth, path = tc.bound_method, tc.bound_path
        else:
            meth, path, skip_reason = _method_path_from_action(
                tc.action,
                title=tc.title or "",
                input_data=tc.input_data,
            )

        # Layer A — SurfaceMap state-skip guard at materialization time.
        # If the binding for this test's REQ is anything other than
        # BACKEND_API, the pytest harness cannot exercise the requirement
        # honestly. Emit a pytest.skip row (still visible in the artifact)
        # rather than letting it run and contribute a misleading verdict.
        binding = state.surface_map.get(tc.covered_requirement_id) if (
            tc.covered_requirement_id and state.surface_map
        ) else None
        if binding is not None and binding.state != "BACKEND_API":
            skip_reason = (
                f"surface_map[{tc.covered_requirement_id}].state="
                f"{binding.state}; pytest harness cannot exercise this surface honestly"
            )

        # Hard skip with explicit reason instead of the old `meth or "POST"`,
        # `path or "/"` silent-failure defaults — those produced ghost rows
        # that ran against the wrong endpoint and polluted posture.
        if not meth or not path:
            skip_reason = skip_reason or "no bound_method/bound_path and inference failed"
        slug_base = _slug_from_test_id(tc.test_id)
        slug = slug_base
        dup = 0
        while slug in used_slugs:
            dup += 1
            slug = f"{slug_base}_{dup}"
        used_slugs.add(slug)

        title_one = (tc.title or "").replace("\n", " ").replace("\r", "")[:400]

        # P0-3 (Cursor) — extract the `_repeat` sentinel as a SEPARATE
        # template field so the rendered pytest actually loops. Previously
        # `_payload_python_literal` stripped `_repeat` from the embedded
        # payload and the template did a single request, so REQ-002's
        # "100 failed login attempts, no lockout" AC was untested.
        # The literal payload (passed via `payload_literal`) is still
        # stripped of `_repeat` — that's correct, _repeat isn't a real
        # HTTP field. But the loop count is now propagated to the template.
        repeat_count = 1
        if isinstance(tc.input_data, dict):
            raw = tc.input_data.get("_repeat")
            if raw is not None:
                try:
                    repeat_count = max(1, int(raw))
                except (TypeError, ValueError):
                    repeat_count = 1
        # Hard cap so a Generator hallucinating _repeat=1000000 doesn't
        # take a Cloud Run Job's full timeout budget.
        repeat_cap_env = get_settings().sentinel_pytest_repeat_cap
        try:
            repeat_cap = max(1, int(repeat_cap_env))
        except ValueError:
            repeat_cap = 200
        repeat_count = min(repeat_count, repeat_cap)

        workflow_steps: List[Dict[str, Any]] = []
        if tc.workflow_steps and len(tc.workflow_steps) >= 2:
            for step in tc.workflow_steps:
                ws: Dict[str, Any] = {
                    "method": (step.method or "GET").upper(),
                    "path": step.path or "/",
                    "input_data": step.input_data if isinstance(step.input_data, dict) else {},
                    "expected_status_code": int(step.expected_status_code),
                }
                if step.capture_json_key:
                    ws["capture_json_key"] = step.capture_json_key
                if step.expected_json_keys:
                    ws["expected_json_keys"] = list(step.expected_json_keys)
                workflow_steps.append(ws)

        rows.append(
            {
                "slug": slug,
                "test_id": tc.test_id,
                "title_one_line": title_one,
                "workflow_steps": workflow_steps,
                # When skip_reason is set, the template's pytest.skip fires
                # before any request is made — so the method/path placeholders
                # below are inert. Keep them non-empty strings so the Jinja
                # template can still render without a NoneType error.
                "method": (meth or "GET") if not skip_reason else "GET",
                "path": (path or "/") if not skip_reason else "/",
                "skip_reason": skip_reason,
                "payload_literal": _payload_python_literal(tc.input_data),
                "expected_status_code": tc.expected_status_code,
                # Full set of "neutralized" status codes for adversarial tests
                # (empty list for functional tests). When non-empty, the Jinja
                # template asserts `status_code in [...]` instead of `==`.
                # Without this the suite reports false-positive vulnerabilities
                # whenever the app neutralizes via 401 (auth-route) or 422
                # (Pydantic) instead of the single hardcoded code.
                "acceptable_status_codes": (
                    _acceptable_status_codes_for_adversarial(tc)
                    if tc.is_adversarial else []
                ),
                "forbidden": list(tc.forbidden_response_content or []),
                "is_adversarial": tc.is_adversarial,
                "use_auth": _infer_use_auth(tc),
                # P0-3 — when > 1, the template wraps the request+asserts in
                # a `for _iter in range(N)` loop. 1 = single-shot (default).
                "repeat_count": repeat_count,
                # Stage-3 — honest header attestation. Carries the dict the
                # template's _required_headers block consumes; defaults to
                # {} which the template's `{% if %}` evaluates False on.
                "required_response_headers": dict(
                    getattr(tc, "required_response_headers", None) or {}
                ),
            }
        )

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=False,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    tpl = env.get_template("pytest_api.jinja2")
    rendered = tpl.render(tests=rows)

    out_path = run_dir / "test_sentinel_api_generated.py"
    out_path.write_text(rendered, encoding="utf-8")

    state.metadata["security_compiler_workspace"] = str(root)
    state.metadata["security_compiler_run_dir"] = str(run_dir.resolve())
    if truncated:
        state.metadata["security_compiler_truncated"] = True

    try:
        py_compile.compile(str(out_path), doraise=True)
    except py_compile.PyCompileError as exc:
        logger.error("Generated pytest failed py_compile: %s", exc)
        state.metadata["security_compiler_py_compile_error"] = str(exc)
        return

    paths = list(state.metadata.get("security_compiler_generated_files") or [])
    paths.append(str(out_path.resolve()))
    state.metadata["security_compiler_generated_files"] = paths
    logger.info(
        "security_compiler wrote %s (%d tests, truncated=%s)",
        out_path,
        len(rows),
        truncated,
    )


def _functional_tests_for_requirement(
    tests: List[TestCase], requirement_id: str
) -> List[TestCase]:
    return [
        t
        for t in tests
        if not t.is_adversarial and t.covered_requirement_id == requirement_id
    ]


def _string_input_fields(tc: TestCase) -> List[str]:
    data = tc.input_data
    if not isinstance(data, dict):
        return []
    return [k for k, v in data.items() if isinstance(v, str)]


def _mutate(
    base: TestCase,
    payload: Payload,
    risk: SecurityRisk,
    counter: int,
) -> TestCase:
    """Return an adversarial clone of `base` with string inputs replaced by the payload."""

    raw = base.input_data
    if isinstance(raw, dict):
        mutated_input = copy.deepcopy(raw)
    else:
        mutated_input = {"__value__": raw}

    mutated_fields = _string_input_fields(base)

    if mutated_fields:
        for field in mutated_fields:
            mutated_input[field] = payload.value
    else:
        mutated_input["__adversarial_probe__"] = payload.value
        mutated_fields = ["__adversarial_probe__"]

    owasp_short = risk.owasp_id.split(":", maxsplit=1)[0].strip().upper()
    resilience_key = _OWASP_TO_RESILIENCE_KEY.get(owasp_short, "A04_INSECURE_DESIGN")

    resilience_sig = RESILIENCE_SIGNATURES.get(resilience_key, {})
    vuln_sig = VULNERABILITY_SIGNATURES.get(resilience_key, {})

    return TestCase(
        test_id=f"SEC-{risk.owasp_id.split(':')[0]}-{base.test_id}-{counter}",
        title=f"[{payload.technique}] {base.title}",
        action=base.action,
        input_data=mutated_input,
        expected_result=(
            f"Attack is neutralised: {payload.expected_signal}. "
            f"Original success path ('{base.expected_result}') must NOT occur "
            f"with an attacker-controlled value."
        ),
        expected_status_code=resilience_sig.get("http_status", [200])[0],
        expected_json_keys=[],
        forbidden_response_content=resilience_sig.get("forbidden_keywords", []),
        resilience_signature=(
            f"Status code in {resilience_sig.get('http_status', [200])}. "
            f"Forbidden keywords: {', '.join(resilience_sig.get('forbidden_keywords', []))}. "
            f"Behavior: {resilience_sig.get('expected_behavior', 'N/A')}"
        ),
        vulnerability_signature=(
            f"Status code {vuln_sig.get('http_status', [200])[0]} with leaked data. "
            f"Contains keywords: {', '.join(vuln_sig.get('expected_keywords', []))}. "
            f"Behavior: {vuln_sig.get('expected_behavior', 'N/A')}"
        ),
        coverage_rationale=(
            f"Adversarial mutation of {base.test_id} targeting {payload.exploit_target}. "
            f"Technique: {payload.technique}. "
            f"Risk rationale (from Critic): {risk.rationale}"
        ),
        covered_requirement_id=base.covered_requirement_id,
        covered_acceptance_criterion=base.covered_acceptance_criterion,
        source_refs=list(base.source_refs),
        test_category="security",
        is_adversarial=True,
        owasp_category=risk.owasp_id,
        payload=payload.value,
        exploit_target=payload.exploit_target,
        mutated_fields=mutated_fields,
        parent_test_id=base.test_id,
        attestation_mode="defense_confirming",
    )


def _candidate_tests_for_risk(state: ProjectState, risk: SecurityRisk) -> List[TestCase]:
    functional = [t for t in state.test_suite if not t.is_adversarial]
    if not risk.affected_requirements:
        return functional

    targeted: List[TestCase] = []
    for req_id in risk.affected_requirements:
        targeted.extend(_functional_tests_for_requirement(functional, req_id))
    return targeted or functional


# --------------------------------------------------------------------------- #
# 0.2 — stack-aware payload gating                                            #
# --------------------------------------------------------------------------- #
#
# The mutation engine fans out SQLi/XSS/Command/NoSQL payloads against every
# bound endpoint. On a FastAPI + SQLAlchemy + SQLite app there is no shell
# exec and no document store, so Command-injection and NoSQL-injection
# payloads test for vulnerability classes that physically cannot exist —
# pure denominator padding + spurious errors (observed: lifecycle had 10
# Command + 10 NoSQL clones, ~all trivially resilient or errored).
#
# We probe the target ONCE per run for capability signatures and skip the
# payload classes the stack can't express. Computed at node start, cached on
# state.metadata["stack_capabilities"], consumed in the mutation loop.

_STACK_SIGNATURES = {
    "nosql": (
        "pymongo", "mongoengine", "motor", "mongomock", "from mongo",
        "import mongo", "mongoclient", "mongoose", "$where", "collection.find(",
        "couchdb", "dynamodb", "boto3.resource('dynamodb'", "redis.",
    ),
    "shell": (
        "subprocess", "os.system", "os.popen", "child_process", "shell=true",
        "popen(", "commands.getoutput", "pty.spawn", "exec(", "eval(",
    ),
}

# Map a payload's exploit_target → the capability it requires. If the target
# stack lacks that capability, the payload class is skipped.
_PAYLOAD_CLASS_REQUIRES = {
    "(NoSQL)": "nosql",
    "(Command)": "shell",
}


def _detect_stack_capabilities(roots: List[Path]) -> Dict[str, bool]:
    """One-pass probe of the target source for stack capabilities.

    Returns e.g. {"sql": True, "nosql": False, "shell": False}. SQL defaults
    True (the demo app is SQL and SQLi is always worth probing); nosql/shell
    are True only if a real signature appears in the indexed source.
    """
    found = {"nosql": False, "shell": False}
    exts = {".py", ".js", ".ts", ".jsx", ".tsx"}
    skip_dirs = {"venv", ".venv", "node_modules", "__pycache__", ".git", "dist", "build"}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in exts:
                continue
            if any(part in skip_dirs for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                continue
            for cap, sigs in _STACK_SIGNATURES.items():
                if not found[cap] and any(s in text for s in sigs):
                    found[cap] = True
            if all(found.values()):
                break
    return {"sql": True, **found}


def _payload_allowed_by_stack(
    payload: "Payload",
    stack: Dict[str, bool],
) -> Optional[str]:
    """Return None if the payload's class is exercisable on this stack,
    else a skip-reason. Only NoSQL/Command are gated; SQLi/XSS/etc. always
    pass (relevant to any HTTP API)."""
    target = payload.exploit_target or ""
    for marker, cap in _PAYLOAD_CLASS_REQUIRES.items():
        if marker in target and not stack.get(cap, False):
            return f"stack lacks '{cap}' capability — {marker} payload not exercisable"
    return None


def _can_mutate(
    base: TestCase,
    risk: SecurityRisk,
    surface_map: Dict[str, SurfaceBinding],
) -> Optional[str]:
    """Layer A — gate adversarial mutation against the SurfaceMap.

    Returns None if the mutation is allowed, otherwise a skip-reason string.
    The Compiler must not turn a functional test for REQ-001 (bound to
    /tasks/) into a SEC-A03-TC-REQ-005-* test on /register just because the
    Critic flagged A03 against REQ-005. That cross-REQ leak is what the
    search story's 6 "REQ-005 register-probe" tests were — Rule 11 alone on
    the Generator cannot stop them because the Compiler manufactures them
    from a Generator-correct base test.

    Three gates:
      1. binding for base's REQ must exist and be BACKEND_API
      2. base's bound_path (stamped by Generator validation) must be in
         binding.backend_endpoints
      3. risk must list base's REQ in affected_requirements (or have no
         scope, in which case we permit but log)
    """
    target_req = base.covered_requirement_id
    if not target_req or not surface_map:
        return None  # back-compat: unbound / no map → pass through
    binding = surface_map.get(target_req)
    if binding is None:
        return None
    if binding.state != "BACKEND_API":
        return f"surface_map[{target_req}].state={binding.state} — adversarial mutation forbidden"
    # App-wide defenses (TRANSPORT, ERROR_SANITIZATION) sentinel `path: "/"`
    # — the defense applies across every route, so the mutation may target
    # any path the Generator wrote.
    _paths = {(ep.path or "").strip() for ep in binding.backend_endpoints}
    _app_wide = binding.defense_kind in ("TRANSPORT", "ERROR_SANITIZATION") and _paths.issubset({"/", ""})
    if base.bound_path and not _app_wide:
        from ._paths import _paths_match_any
        if not _paths_match_any(base.bound_path, [ep.path for ep in binding.backend_endpoints]):
            return (f"base test's bound_path {base.bound_path} not in binding endpoints "
                    f"{[ep.path for ep in binding.backend_endpoints]}")
    # Risk scope: if affected_requirements is set, base's REQ must be in it.
    # Empty affected_requirements is a Critic loophole — permit, but flag.
    if risk.affected_requirements and target_req not in risk.affected_requirements:
        return (f"risk {risk.owasp_id} affects {risk.affected_requirements}, "
                f"not {target_req}")
    return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def security_compiler_node(state: ProjectState) -> ProjectState:
    """OWASP adversarial expansion + Jinja pytest materialization (httpx live server).

    PRE_CODE mode: produce SecurityChecklistItems from Critic's SecurityRisks,
    store in state.security_checklist, skip all mutation and pytest generation.
    POST_CODE mode: unchanged — mutate functional tests + materialize pytest file.
    """

    # ------------------------------------------------------------------
    # PRE_CODE branch — produces SecurityChecklistItems, no test mutation,
    # no pytest materialization (no codebase exists yet to run against)
    # ------------------------------------------------------------------
    if state.pipeline_mode == "PRE_CODE":
        if not state.security_risks:
            state.metadata["security_compiler_skipped"] = (
                "PRE_CODE: no security_risks in state"
            )
            return state

        req_lookup = {r.requirement_id: r for r in state.validated_requirements}

        llm = get_local_llm(temperature=0.0, json_mode=True, seed=42)
        checklist: List[SecurityChecklistItem] = []
        failed_risks: List[str] = []

        for risk in state.security_risks:
            req_ids = risk.affected_requirements or [
                r.requirement_id for r in state.validated_requirements
            ]

            for req_id in req_ids:
                req = req_lookup.get(req_id)
                if req is None:
                    continue

                statement = getattr(req, "statement", str(req))
                acceptance_criteria = getattr(req, "acceptance_criteria", "")
                if isinstance(acceptance_criteria, list):
                    acceptance_criteria = "; ".join(str(ac) for ac in acceptance_criteria)

                try:
                    items = _call_llm_for_checklist_items(
                        llm=llm,
                        risk=risk,
                        requirement_id=req_id,
                        statement=statement,
                        acceptance_criteria=acceptance_criteria,
                    )
                    checklist.extend(items)
                except LLMInvocationError as exc:
                    failed_risks.append(
                        f"{risk.owasp_id}/{req_id}: provider error after retries: {exc}"
                    )
                except Exception as exc:
                    failed_risks.append(f"{risk.owasp_id}/{req_id}: {exc}")

        state.security_checklist.extend(checklist)
        state.metadata["security_compiler_mode"] = "PRE_CODE"
        state.metadata["security_compiler_checklist_generated"] = len(checklist)
        if failed_risks:
            state.metadata["security_compiler_failed_risks"] = failed_risks

        return state

    # ------------------------------------------------------------------
    # POST_CODE branch — original logic, completely unchanged
    # ------------------------------------------------------------------

    if not state.test_suite:
        state.metadata["security_compiler_skipped"] = "empty test_suite"
        return state

    adversarial: List[TestCase] = []
    unmatched_risks: List[str] = []

    # 0.2 — compute stack capabilities ONCE (not per-mutation). The probe
    # walks the TARGET-UNDER-TEST source for NoSQL/shell signatures; the
    # mutation loop reads the cached flags to skip payload classes the stack
    # can't express.
    #
    # CRITICAL: scan ONLY the target app (repo_cache), NOT the Backend/
    # pipeline source. The pipeline's own code (this file's _STACK_SIGNATURES,
    # utils/payloads.py) literally contains the words "pymongo", "subprocess",
    # "mongo", etc. — scanning Backend made every capability read True and
    # silently disabled gating (observed: stack={sql,nosql,shell all True} on
    # a FastAPI+SQLite target). The target is the app the tests run against.
    _backend_root = Path(__file__).resolve().parent.parent
    _target_root = _backend_root / "repo_cache"
    _stack = _detect_stack_capabilities([_target_root])
    state.metadata["stack_capabilities"] = _stack
    _payloads_gated: List[Dict[str, Any]] = []

    # Layer A — Compiler-side Rule 11 enforcement.
    # The Generator's Rule 11 stops off-binding tests at LLM output time.
    # But adversarial tests are NOT from the Generator — they're synthesized
    # here by mutating functional tests. Without _can_mutate, the Compiler
    # happily produces SEC-A03-TC-REQ-005-* tests on /register from a /tasks/
    # functional base, which is the exact "REQ-005 register-probe" failure
    # mode the SurfaceMap was built to close. Gate every mutation against
    # the binding for the base test's covered_requirement_id.
    mutations_skipped: List[Dict[str, Any]] = []

    if state.security_risks and any(not t.is_adversarial for t in state.test_suite):
        for risk in state.security_risks:
            payloads = get_payloads(risk.owasp_id)
            if not payloads:
                unmatched_risks.append(risk.owasp_id)
                continue

            candidates = _candidate_tests_for_risk(state, risk)
            if not candidates:
                unmatched_risks.append(
                    f"{risk.owasp_id} (no functional tests matched affected_requirements)"
                )
                continue

            counter = 0
            for base in candidates:
                skip_reason = _can_mutate(base, risk, state.surface_map)
                if skip_reason:
                    mutations_skipped.append({
                        "base_test_id": base.test_id,
                        "base_requirement_id": base.covered_requirement_id,
                        "risk_owasp_id": risk.owasp_id,
                        "reason": skip_reason,
                    })
                    continue
                for payload in payloads:
                    # 0.2 — skip payload classes the stack can't express
                    # (NoSQL on a SQL app, Command on a no-shell app).
                    stack_skip = _payload_allowed_by_stack(payload, _stack)
                    if stack_skip:
                        _payloads_gated.append({
                            "base_test_id": base.test_id,
                            "exploit_target": payload.exploit_target,
                            "reason": stack_skip,
                        })
                        continue
                    counter += 1
                    mutant = _mutate(base, payload, risk, counter)
                    # Propagate the binding stamps so downstream Compiler
                    # materialization + Classifier tier 0 see them.
                    mutant.bound_method = base.bound_method
                    mutant.bound_path = base.bound_path
                    mutant.bound_surface_state = base.bound_surface_state
                    adversarial.append(mutant)

        cap_adv = _max_adversarial()
        if len(adversarial) > cap_adv:
            adversarial = adversarial[:cap_adv]
            state.metadata["security_compiler_adversarial_truncated_to"] = cap_adv
        state.test_suite.extend(adversarial)
        state.metadata["security_compiler_adversarial_count"] = len(adversarial)
        if unmatched_risks:
            state.metadata["security_compiler_unmatched_risks"] = unmatched_risks
        if mutations_skipped:
            state.metadata["security_compiler_mutations_skipped"] = mutations_skipped
        if _payloads_gated:
            state.metadata["security_compiler_payloads_gated_by_stack"] = _payloads_gated
            state.metadata["security_compiler_payloads_gated_count"] = len(_payloads_gated)
    else:
        if not state.security_risks:
            state.metadata["security_compiler_adversarial_count"] = 0
            state.metadata["security_compiler_note"] = (
                "no security_risks — emitted pytest contains functional tests only"
            )
        else:
            state.metadata["security_compiler_skipped_mutations"] = (
                "no functional tests in suite to mutate"
            )
            state.metadata["security_compiler_adversarial_count"] = 0

    try:
        _materialize_pytest_workspace(state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("security_compiler: materialize step failed")
        state.metadata["security_compiler_materialize_error"] = f"{type(exc).__name__}: {exc}"

    return state