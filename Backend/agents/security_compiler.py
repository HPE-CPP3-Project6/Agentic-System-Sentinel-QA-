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
import os
import py_compile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader
from langchain_core.prompts import ChatPromptTemplate

from state import ProjectState, SecurityRisk, SecurityChecklistItem, TestCase
from utils import (
    LLMInvocationError,
    Payload,
    get_local_llm,
    get_payloads,
    invoke_with_retry,
    parse_llm_json,
    stringify_response,
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
    raw = os.getenv("SENTINEL_WORKSPACE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_BACKEND_ROOT / "workspace").resolve()


def _max_tests_per_file() -> int:
    raw = os.getenv("SENTINEL_COMPILER_MAX_TESTS_PER_FILE", "80")
    try:
        return max(1, min(500, int(raw)))
    except ValueError:
        return 80


def _max_adversarial() -> int:
    """Cap adversarial rows before extend (matches .env.example SENTINEL_COMPILER_MAX_ADVERSARIAL)."""

    raw = os.getenv("SENTINEL_COMPILER_MAX_ADVERSARIAL", "200")
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


def _method_path_from_action(action: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Infer (method, path, skip_reason). skip_reason set when inference fails."""

    text = (action or "").strip()
    combined = re.compile(
        r"\b(GET|POST|PUT|PATCH|DELETE)\b\s*[^\n/]*?(/[A-Za-z0-9_\-./]+)",
        re.IGNORECASE | re.DOTALL,
    )
    m = combined.search(text)
    if m:
        meth = m.group(1).upper()
        path = m.group(2).strip()
        if "{" in path or "}" in path:
            return None, None, "Path contains `{`/`}` placeholders — not supported in generated httpx tests"
        if not path.startswith("/"):
            path = "/" + path.lstrip("/")
        return meth, path, None

    path_m = re.search(r"(/[A-Za-z][A-Za-z0-9_/\-]{0,200})", text)
    if path_m:
        path = path_m.group(1)
        if "{" in path or "}" in path:
            return None, None, "Path contains placeholders"
        return "POST", path, None

    return None, None, "Could not infer HTTP method and path from action: " + text[:220]


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
        tests_all = tests_all[:cap]
        truncated = True
        state.metadata["security_compiler_tests_truncated_to"] = cap

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
        meth, path, skip_reason = _method_path_from_action(tc.action)
        slug_base = _slug_from_test_id(tc.test_id)
        slug = slug_base
        dup = 0
        while slug in used_slugs:
            dup += 1
            slug = f"{slug_base}_{dup}"
        used_slugs.add(slug)

        title_one = (tc.title or "").replace("\n", " ").replace("\r", "")[:400]

        rows.append(
            {
                "slug": slug,
                "test_id": tc.test_id,
                "title_one_line": title_one,
                "method": meth or "POST",
                "path": path or "/",
                "skip_reason": skip_reason,
                "payload_literal": _payload_python_literal(tc.input_data),
                "expected_status_code": tc.expected_status_code,
                "forbidden": list(tc.forbidden_response_content or []),
                "is_adversarial": tc.is_adversarial,
                "use_auth": _infer_use_auth(tc),
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
        is_adversarial=True,
        owasp_category=risk.owasp_id,
        payload=payload.value,
        exploit_target=payload.exploit_target,
        mutated_fields=mutated_fields,
        parent_test_id=base.test_id,
    )


def _candidate_tests_for_risk(state: ProjectState, risk: SecurityRisk) -> List[TestCase]:
    functional = [t for t in state.test_suite if not t.is_adversarial]
    if not risk.affected_requirements:
        return functional

    targeted: List[TestCase] = []
    for req_id in risk.affected_requirements:
        targeted.extend(_functional_tests_for_requirement(functional, req_id))
    return targeted or functional


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
                for payload in payloads:
                    counter += 1
                    adversarial.append(_mutate(base, payload, risk, counter))

        cap_adv = _max_adversarial()
        if len(adversarial) > cap_adv:
            adversarial = adversarial[:cap_adv]
            state.metadata["security_compiler_adversarial_truncated_to"] = cap_adv
        state.test_suite.extend(adversarial)
        state.metadata["security_compiler_adversarial_count"] = len(adversarial)
        if unmatched_risks:
            state.metadata["security_compiler_unmatched_risks"] = unmatched_risks
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