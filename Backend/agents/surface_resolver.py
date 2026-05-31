"""Surface Resolver — Agent 1.5 in the Sentinel-QA pipeline.

Sits between Critic and Generator. Reads the validated_requirements +
security_risks from the Critic, performs a per-REQ RAG sweep over the
indexed codebase, and asks the LLM to bind each requirement to ONE of:

    BACKEND_API        — implemented as a real backend endpoint
    FRONTEND_ONLY      — rendered UI but no logic (Layer C track)
    CLIENT_SIDE_ONLY   — logic in browser, no backend to test
    NOT_IMPLEMENTED    — story names something not in the codebase
    NEEDS_CLARIFICATION — ambiguous mapping or contradiction

The output `state.surface_map` becomes BINDING STATE for every downstream
agent. Generator may only emit tests against bound surfaces (Rule 11).
Compiler refuses to mutate tests whose binding state is not BACKEND_API.
Classifier marks tests off_target if their request path falls outside the
bound endpoints. This is what eliminates the proxy-test / false-positive-
vulnerability family of bugs at the seam, instead of in each agent.

PRE_CODE mode skips the LLM call entirely — the Critic's DesignContracts
ARE the surface map for shift-left use. POST_CODE persists are loaded
from phase1 snapshots and overwritten by the live resolver result.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.prompts import ChatPromptTemplate

from database import (
    RouteIntent,
    SourceSnippet,
    VerticalSliceContext,
    get_or_create_collection,
    query_source_context,
)
from state import (
    ACOverride,
    BackendEndpoint,
    DesignContract,
    FrontendSurface,
    ProjectState,
    SurfaceBinding,
    SurfaceState,
    ValidatedRequirement,
)
from utils import (
    LLMInvocationError,
    get_local_llm,
    invoke_with_retry,
    parse_llm_json,
    stringify_response,
)

logger = logging.getLogger(__name__)


SURFACE_RESOLVER_SYSTEM_PROMPT = """You are the Surface Resolver — Agent 1.5 in the
Sentinel-QA pipeline.

Your job is to map EACH REQUIREMENT to the concrete TESTABLE SURFACE in the
codebase. You do NOT write tests. You output a typed plan that downstream
agents (Generator, Compiler, Classifier) will be STRUCTURALLY BOUND TO.

============================================================
RULE 0 — THREAT-CLASS CLASSIFICATION (do this FIRST)
============================================================

Before choosing a SurfaceState for each requirement, classify its
THREAT CLASS. This decision dominates the downstream binding.

  DEFENSIVE_NORMAL
    The requirement describes a normal feature (login flow, search
    results, registration). The security test exercises the feature
    the way users would. Proceed to surface selection as usual.

  ── ACCEPT-IS-SECURE GUARD (read before choosing DEFENSIVE_INVERTED) ──
    Some requirements ask the app to ACCEPT input that LOOKS dangerous
    but is SAFELY PROCESSED — the secure outcome is SUCCESS (2xx), not
    rejection. These are DEFENSIVE_NORMAL, NOT DEFENSIVE_INVERTED /
    INPUT_REJECTION.

    Litmus test: "What is the SECURE response status?"
      • Secure behavior = REJECT the input (4xx)  → DEFENSIVE_INVERTED,
        kind INPUT_REJECTION. e.g. "accept any LENGTH" → reject >255 (422).
      • Secure behavior = ACCEPT the input (2xx) and neutralize it
        downstream (bcrypt hash, parameterized query, output encoding)
        → DEFENSIVE_NORMAL. The special characters are stored/processed
        safely; the request SUCCEEDS.

    Canonical DEFENSIVE_NORMAL examples (do NOT mark INPUT_REJECTION):
      • "must accept passwords containing %, ;, ', -- " — registration
        SUCCEEDS (201); bcrypt hashes the value, no SQL injection. The
        chars are valid password content, not an attack to reject.
      • "must accept unicode / emoji in a free-text field" — stored as-is.
      • "must accept any valid email format" — accepted (201).

    Rule: classify INPUT_REJECTION ONLY when the app SHOULD return 4xx.
    If the correct, secure behavior is a 2xx that safely processes the
    input, it is DEFENSIVE_NORMAL — a normal feature test, not an
    anti-pattern inversion. (Observed mis-classification: login REQ-003
    "accept passwords with special chars" was wrongly tagged
    INPUT_REJECTION, so the correct 201 test was dropped by the
    Generator's status-code gate.)

  DEFENSIVE_INVERTED
    The requirement uses ANTI-PATTERN language. The narrator is
    asking for an insecure behavior; the Critic flagged it as a
    security risk precisely because the INVERSE (rejection /
    enforcement / hiding) is the DEFENSE.

    Defenses come in FIVE distinct KINDS. You MUST classify which
    kind applies and emit `defense_kind` so the Generator can write
    the right test shape (status code, assertion type, etc.). The
    five kinds and how they manifest:

    ┌─────────────────────────┬──────────────────────────────────────────┐
    │ defense_kind            │ Manifestation                            │
    ├─────────────────────────┼──────────────────────────────────────────┤
    │ INPUT_REJECTION         │ 4xx + clean body. Defense rejects bad    │
    │                         │ input before processing.                 │
    │                         │   • length / format validation → 422     │
    │                         │   • auth gate failure       → 401        │
    │                         │   • authorization gate      → 403        │
    │                         │   • rate-limit              → 429        │
    │                         │ Example stories:                         │
    │                         │   "accept any length"  → 422 over 255    │
    │                         │   "unlimited retries"  → 429 after N     │
    │                         │                                          │
    │ TRANSPORT               │ 3xx + transport-security header.         │
    │                         │ Defense forces protocol upgrade or       │
    │                         │ rejects insecure transport.              │
    │                         │   • HTTPS redirect      → 301/302        │
    │                         │   • HSTS header         → present        │
    │                         │   • Secure cookie flag  → present        │
    │                         │ Example: "session token via HTTP" →      │
    │                         │   301 to https:// with HSTS              │
    │                         │                                          │
    │ OUTPUT_REDACTION        │ 200 + forbidden_response_content list.   │
    │                         │ Defense lets the request succeed but     │
    │                         │ strips sensitive content from the body.  │
    │                         │   • response_model excludes a field      │
    │                         │   • serializer aliases / hides fields    │
    │                         │   • exclude_none / by_alias              │
    │                         │ Example: "show internal IDs / system     │
    │                         │   fields" → 200 + ["password_hash",      │
    │                         │   "user_id"] absent from response        │
    │                         │                                          │
    │ IMPLICIT_FILTER         │ 200 + assert filtered/empty result.      │
    │                         │ Defense scopes the query so unauthorized │
    │                         │ rows never appear in the response.       │
    │                         │   • Task.user_id == current_user.id      │
    │                         │   • soft-delete (deleted_at IS NULL)     │
    │                         │   • tenant scoping                       │
    │                         │ Example: "show all users' records" →     │
    │                         │   200 + items=[] for an unauthorized     │
    │                         │   peer's data                            │
    │                         │                                          │
    │ ERROR_SANITIZATION      │ 5xx + forbidden_response_content list.   │
    │                         │ Defense lets the error surface but       │
    │                         │ scrubs sensitive details from the body.  │
    │                         │   • global exception handler             │
    │                         │   • generic 500 message                  │
    │                         │   • DEBUG=False in production            │
    │                         │ Example: "leak SQL in errors" → 500 +    │
    │                         │   ["Traceback", "psycopg2", "sqlite3.",  │
    │                         │   "SQLSTATE"] absent from response       │
    └─────────────────────────┴──────────────────────────────────────────┘

    For DEFENSIVE_INVERTED you MUST:
      1. Find the endpoint where the DEFENSE lives in the retrieved
         code (Pydantic validator, response_model, auth gate, rate-
         limit, exception handler, redirect middleware, ORM filter).

         SPECIAL CASE — APP-WIDE DEFENSES (no URL path):
         Global exception handlers, redirect middleware, and CORS /
         HSTS / SessionMiddleware registrations are not bound to a
         specific URL path. For these, use `path: "/"` as a sentinel
         and put the file in `handler_file`. Example for an
         ERROR_SANITIZATION defense:
            {{ "method": "POST", "path": "/",
               "handler_file": "main.py", "handler_line": 74 }}
         The Generator will choose a concrete URL to actually fire
         the request against (typically one that the Critic flagged).

      2. Bind state = BACKEND_API (not NOT_IMPLEMENTED) to THAT endpoint.
      3. Emit anti_pattern_summary — ONE sentence naming the story's
         insecure ask.
      4. Emit defense_kind — pick ONE from the five kinds above.
      5. Emit defense_assertion — ONE sentence describing what a
         defense-confirming response looks like, matching the kind:
            INPUT_REJECTION   → "POST /register returns 422 when
                                  email > 255 chars; no Traceback"
            TRANSPORT         → "GET / served on http:// returns 301
                                  to https:// with Strict-Transport-
                                  Security header"
            OUTPUT_REDACTION  → "GET /tasks/ returns 200; response body
                                  contains 'items' but NOT
                                  'password_hash' or 'deleted_at'"
            IMPLICIT_FILTER   → "GET /tasks/ as user A returns 200
                                  with items=[]; tasks owned by user B
                                  are not present"
            ERROR_SANITIZATION→ "POST /register with bad input that
                                  triggers DB error returns 500 with
                                  generic message; no 'psycopg2' or
                                  'Traceback' in body"

  NON_FUNCTIONAL
    Property assertion that no single endpoint owns ("no PII in any
    response", "every action must be audited"). → state =
    NEEDS_CLARIFICATION; threat_class = NON_FUNCTIONAL.

DEFENSIVE_INVERTED GATE (anti-fabrication):
    To classify as DEFENSIVE_INVERTED you need BOTH:
      a) the Critic listed a security risk against this requirement, AND
      b) retrieval contains a real defense mechanism (validator code,
         length-cap declaration, rate-limit, exception handler,
         redirect/HSTS middleware) that could enforce the inverse.

    Without BOTH, the answer is NOT_IMPLEMENTED. Inventing a "defense"
    that doesn't appear in retrieved code is forbidden — that's the
    proxy-test failure mode in disguise. If the defense literally is
    not in the code, the app cannot demonstrate it and the binding is
    NOT_IMPLEMENTED.

This rule SUPERSEDES the surface-state choice in literal cases. The
search REQ-005 ("must leak SQL errors") becomes DEFENSIVE_INVERTED +
BACKEND_API on the global exception handler, NOT NOT_IMPLEMENTED, IFF
the handler appears in retrieval.

============================================================
SURFACE STATES (pick exactly one per requirement)
============================================================

  BACKEND_API
    A real backend endpoint exists for this requirement. List the
    endpoints (method + path + handler file:line + schema names) the
    requirement maps to.

  FRONTEND_ONLY
    UI element only — a static display, navigation, or pure rendering
    with no logic to verify at the API or behavior layer.

  CLIENT_SIDE_ONLY
    Logic lives in the browser (e.g. `.filter()` over a local array,
    in-memory parsing). There is NO backend route that implements this
    requirement, so an HTTP test cannot exercise it honestly.

  NOT_IMPLEMENTED
    The requirement names something (route, feature, screen) that does
    NOT exist in the retrieved codebase. The requirement is a wish, not
    a testable thing.

  NEEDS_CLARIFICATION
    Multiple plausible mappings exist OR the requirement is cross-cutting
    (e.g. "errors should not leak SQL" — no single endpoint owns this).
    A stakeholder must decide before tests can be written.

============================================================
CRITICAL DISCIPLINE
============================================================

1. GROUND OR DON'T CLAIM. You may ONLY cite routes/components present in
   the retrieved SOURCE CONTEXT. Inventing /share or /organization
   because the story mentions them is FORBIDDEN — that's NOT_IMPLEMENTED.

2. LANGUAGE DRIFT IS REAL. The story's language and the code's language
   often differ. "Search" in a story may be implemented as
   `String.prototype.includes()` in Dashboard.jsx. That binding is
   CLIENT_SIDE_ONLY, NOT BACKEND_API on the nearest /tasks/ route.
   Choosing a near-miss endpoint is the proxy-test failure mode this
   agent exists to prevent.

3. GROUNDING REQUIRED. Every binding MUST cite at least one file:line in
   `grounding_refs`. No grounding → NOT_IMPLEMENTED or NEEDS_CLARIFICATION.

4. CROSS-CUTTING IS CLARIFICATION. A requirement about error-logging,
   "should display X", or "must not contain Y" — without a specific
   endpoint — maps to NEEDS_CLARIFICATION. Do NOT pick a proxy endpoint
   to satisfy the requirement. (This is the REQ-005-on-search failure
   mode.)

4a. DISAMBIGUATION — NOT_IMPLEMENTED IS A LAST RESORT.

    NOT_IMPLEMENTED is the BLUNT INSTRUMENT. Apply it ONLY when
    NEITHER the backend NOR the frontend has any implementation that
    plausibly corresponds to the requirement. Before choosing it, you
    MUST work through three HARD RULES in order. The first one whose
    condition matches WINS — you may not fall through to NOT_IMPLEMENTED
    if any of these fire.

    HARD RULE A — CLIENT_SIDE_ONLY (forcing function):

      IF the retrieved FRONTEND source context literally contains any
      of these tokens AND the requirement names the matching feature
      (search, filter, sort, paginate, lookup):

        .filter(            String.prototype.includes
        .find(              .indexOf(
        .some(  .every(     useMemo(
        .map(   .reduce(    .match(
        Array.from          new Set(
        useState([          useMemo(() =>

      THEN you MUST emit:
        state = "CLIENT_SIDE_ONLY"
        frontend_surfaces = [the component(s) where the token appears]
        rationale = "the feature is implemented in browser via <token>
                     at <file:line>; no backend route handles it"

      NOT_IMPLEMENTED is FORBIDDEN in this case. The feature IS
      implemented — just not on a layer the pytest harness can
      exercise. The artifact reader needs to know "this is a Layer-C
      Playwright story", not "this story is unbuildable."

      This rule exists because Gemini was choosing NOT_IMPLEMENTED for
      the search story's REQ-001 and REQ-004 (observed in
      exec-demo-search-post_code-20260529_073141) even when the
      rationale explicitly cited Dashboard.jsx's Array.prototype.filter.
      The reasoning was right; only the label was wrong. This rule
      forces the label to match the reasoning.

    HARD RULE B — NEEDS_CLARIFICATION:

      IF the requirement is a cross-cutting property assertion that
      no single endpoint or component owns:
        - "errors must not leak X" / "must not expose Y"
        - "every Z must be audited" / "must log every W"
        - "no PII in responses" / "all responses must be encrypted"
        - "error messages should display <something>"

      THEN you MUST emit state = "NEEDS_CLARIFICATION".
      NOT_IMPLEMENTED is FORBIDDEN — the property is testable in
      principle but a stakeholder must say which endpoint to test it
      against. This is the search REQ-005 case.

    HARD RULE C — BACKEND_API ON LANGUAGE-DRIFT:

      IF retrieved BACKEND chunks show a route + request schema +
      handler that plausibly implements the requirement, even when
      the story's noun does NOT literally match the route's noun
      (e.g. story says "search" but the route is GET /tasks/?q=)
      THEN emit BACKEND_API with that route. Language drift is normal.

    NOT_IMPLEMENTED — applies ONLY when ALL of the following hold:
      - no backend route in retrieval implements (or could implement) it
      - no frontend component in retrieval implements it
      - the requirement is NOT a cross-cutting property assertion
      Examples: /share, /organization, /audit-log when those routes
      genuinely have zero presence in retrieval.

5. CONFIDENCE:
     "high"   — exact route + schema + handler match, single grounding
     "medium" — route is clear but schema or path variant ambiguous
     "low"    — grounding is partial; surface state is best-guess
   If confidence is "low" AND state is BACKEND_API, prefer to downgrade
   to NEEDS_CLARIFICATION unless the file:line evidence is solid.

6. PER-AC OVERRIDES. If ACs within ONE requirement disagree on surface
   state (e.g. one AC is client-side filter, another is backend storage),
   set the primary `state` to whichever dominates by AC count, then list
   the dissenting ACs in `ac_overrides`. MVP downstream may ignore the
   overrides — persist them anyway for Day-2 use.

============================================================
OUTPUT SCHEMA — STRICT JSON ONLY (no prose, no fences)
============================================================

{{
  "bindings": [
    {{
      "requirement_id": "REQ-001",
      "state": "BACKEND_API|FRONTEND_ONLY|CLIENT_SIDE_ONLY|NOT_IMPLEMENTED|NEEDS_CLARIFICATION",
      "threat_class": "DEFENSIVE_NORMAL|DEFENSIVE_INVERTED|NON_FUNCTIONAL",
      "anti_pattern_summary": "1 sentence — REQUIRED iff threat_class=DEFENSIVE_INVERTED; else null",
      "defense_kind": "INPUT_REJECTION|TRANSPORT|OUTPUT_REDACTION|IMPLICIT_FILTER|ERROR_SANITIZATION — REQUIRED iff threat_class=DEFENSIVE_INVERTED; else null",
      "defense_assertion": "1 sentence — REQUIRED iff threat_class=DEFENSIVE_INVERTED; else null",
      "backend_endpoints": [
        {{
          "method": "GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS",
          "path": "/tasks/" or "/tasks/{{task_id}}",
          "handler_file": "routers/task_router.py",
          "handler_line": 169,
          "request_schema": "schemas.TaskCreate",
          "response_schema": "schemas.PaginatedTaskResponse"
        }}
      ],
      "frontend_surfaces": [
        {{
          "component": "Dashboard",
          "file": "frontend/src/components/Dashboard.jsx",
          "line": 118,
          "behavior": "client-side filter via String.prototype.includes()"
        }}
      ],
      "rationale": "1-2 sentences citing the grounding evidence.",
      "grounding_refs": ["routers/task_router.py:169-211"],
      "confidence": "high|medium|low",
      "ac_overrides": []
    }}
  ]
}}

For NOT_IMPLEMENTED and NEEDS_CLARIFICATION, set backend_endpoints and
frontend_surfaces to empty lists. confidence MUST still be set; rationale
must explain what was searched and why nothing was found.

threat_class is REQUIRED on every binding.
anti_pattern_summary, defense_kind, and defense_assertion are
REQUIRED when threat_class = DEFENSIVE_INVERTED, null otherwise.
"""


SURFACE_RESOLVER_USER_PROMPT = """Story: {story_title} ({story_id})

User story:
{user_story}

Requirements to map:
{requirements_block}

Security risks predicted by the Critic (these may help disambiguate
which surfaces matter for the security-test pass):
{risks_block}

----- BEGIN SOURCE CONTEXT (UNION OF PER-REQ RETRIEVALS) -----
{source_context}
----- END SOURCE CONTEXT -----

Emit STRICT JSON only, following the schema exactly. One binding per
requirement listed above. No bindings for requirement IDs not listed."""


# --------------------------------------------------------------------------- #
# Retrieval — union of per-REQ slices                                         #
# --------------------------------------------------------------------------- #


def _collect_union_context(
    requirements: List[ValidatedRequirement],
) -> tuple[List[SourceSnippet], List[str]]:
    """Per-REQ retrieval, then dedup by SourceSnippet header.

    Per-REQ retrieval (vs one combined sweep) matches what the Generator
    will see when it later operates per-REQ — same grounding for Resolver
    and Generator, no drift between "what the Resolver bound" and "what the
    Generator could see when writing tests."
    """
    seen_headers: set[str] = set()
    union_snippets: List[SourceSnippet] = []
    origins: List[str] = []
    for req in requirements:
        action = req.statement
        try:
            slice_: VerticalSliceContext = query_source_context(
                action=action,
                n_results=10,
                intent=RouteIntent.UNKNOWN,
            )
        except Exception as exc:  # noqa: BLE001 — retrieval failures must not abort
            logger.warning("surface_resolver retrieval failed for %s: %s",
                           req.requirement_id, exc)
            continue
        for snip in slice_.all_snippets:
            header = snip.header()
            if header in seen_headers:
                continue
            seen_headers.add(header)
            union_snippets.append(snip)
            origins.append(header)
    return union_snippets, origins


def _render_context(snippets: List[SourceSnippet]) -> str:
    """Render the union as a single sectioned block for the prompt."""
    if not snippets:
        return "[no source context retrieved]"
    return "\n\n---\n\n".join(snip.as_prompt_block() for snip in snippets)


def _render_requirements(reqs: List[ValidatedRequirement]) -> str:
    blocks: List[str] = []
    for r in reqs:
        ac_lines = "\n".join(f"    - {ac}" for ac in r.acceptance_criteria) or "    - (none)"
        owasp = ", ".join(r.owasp_mapping) or "(none)"
        blocks.append(
            f"  {r.requirement_id}: {r.statement}\n"
            f"    OWASP: {owasp}\n"
            f"    Acceptance Criteria:\n{ac_lines}"
        )
    return "\n\n".join(blocks)


def _render_risks(risks) -> str:
    if not risks:
        return "  (no security risks predicted)"
    return "\n".join(
        f"  {r.owasp_id} ({r.severity}) — {r.title}: affects {r.affected_requirements or '(unspecified)'}"
        for r in risks
    )


# --------------------------------------------------------------------------- #
# PRE_CODE branch — derive map from DesignContracts                           #
# --------------------------------------------------------------------------- #


def _surface_map_from_design_contracts(
    contracts: List[DesignContract],
) -> Dict[str, SurfaceBinding]:
    """Translate Critic's PRE_CODE DesignContracts into a SurfaceMap.

    In PRE_CODE there is no codebase to ground against; the DC's endpoint+
    method ARE the planned surface. Confidence is "medium" because the code
    doesn't exist yet — the binding is a design intent, not a code fact.
    """
    _VALID_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

    def _split_method_path(dc: DesignContract) -> tuple[str, str]:
        """Design contracts often phrase `endpoint` as 'POST /tasks/' (method +
        path in one string). Split so BackendEndpoint.path is just '/tasks/'
        (otherwise pytest-style routing + path-matching break)."""
        method = (dc.method or "").strip().upper()
        ep = (dc.endpoint or "").strip()
        path = ep
        if ep:
            toks = ep.split()
            # If the endpoint leads with an HTTP method, drop it; take the path token.
            if toks and toks[0].upper() in _VALID_METHODS:
                if not method:
                    method = toks[0].upper()
                path = next((t for t in toks[1:] if t.startswith("/")), ep)
            else:
                path = next((t for t in toks if t.startswith("/")), ep)
        if method not in _VALID_METHODS:
            method = "POST"  # safe default for a creation-style contract
        if path and not path.startswith("/"):
            path = "/" + path
        return method, path

    by_req: Dict[str, List[BackendEndpoint]] = {}
    for dc in contracts:
        method, path = _split_method_path(dc)
        by_req.setdefault(dc.requirement_id, []).append(
            BackendEndpoint(
                method=method,  # type: ignore[arg-type]
                path=path,
                handler_file="(pre-code: not yet implemented)",
                request_schema=", ".join(dc.request_fields.keys()) or None,
                response_schema=", ".join(dc.response_fields.keys()) or None,
            )
        )
    return {
        req_id: SurfaceBinding(
            requirement_id=req_id,
            state="BACKEND_API",
            backend_endpoints=eps,
            rationale="Derived from Critic PRE_CODE DesignContract (design intent, no code yet).",
            grounding_refs=[f"design_contract:{req_id}"],
            confidence="medium",
        )
        for req_id, eps in by_req.items()
    }


# --------------------------------------------------------------------------- #
# Post-LLM validation                                                         #
# --------------------------------------------------------------------------- #


_NON_ROUTE_HANDLER_HINTS = (
    "exception_handler",   # @app.exception_handler(...)
    "add_middleware",      # CORSMiddleware, HTTPSRedirectMiddleware, ...
    "errorhandler",        # Flask-style
    "middleware",          # FastAPI custom middleware
    "@app.middleware",
)


# Allowed values for Literal-typed fields on SurfaceBinding / nested models.
# The Resolver LLM (Gemini Flash) frequently emits these in lowercase or
# mixed case ("output_redaction", "Backend_Api", "Medium"). Pydantic Literal
# validation would silently reject the whole binding. Normalize before
# model_validate so a casing slip doesn't kill the run.
_SURFACE_STATE_VALUES = {
    "BACKEND_API", "FRONTEND_ONLY", "CLIENT_SIDE_ONLY",
    "NOT_IMPLEMENTED", "NEEDS_CLARIFICATION",
}
_THREAT_CLASS_VALUES = {
    "DEFENSIVE_NORMAL", "DEFENSIVE_INVERTED", "NON_FUNCTIONAL",
}
_DEFENSE_KIND_VALUES = {
    "INPUT_REJECTION", "TRANSPORT", "OUTPUT_REDACTION",
    "IMPLICIT_FILTER", "ERROR_SANITIZATION",
}
_CONFIDENCE_VALUES = {"high", "medium", "low"}
_HTTP_METHOD_VALUES = {
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
}


def _coerce_enum(value, allowed: set, case: str = "upper"):
    """Best-effort case normalization for an LLM-emitted enum value.

    Returns the canonical-case string when normalization lands on a member
    of `allowed`; otherwise returns the original value unchanged so
    Pydantic raises a descriptive error the caller can capture.
    """
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if case == "upper":
        candidate = trimmed.upper().replace(" ", "_").replace("-", "_")
    elif case == "lower":
        candidate = trimmed.lower()
    else:
        candidate = trimmed
    if candidate in allowed:
        return candidate
    # Some models reply with "Defense Inverted" or "backend api"; try
    # squashing whitespace + dashes one more time.
    squashed = candidate.replace(" ", "_").replace("-", "_")
    return squashed if squashed in allowed else value


def _normalize_binding_enums(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of `entry` with Literal-typed string fields normalized
    to their canonical case. Safe to call on partial / malformed entries —
    fields that are not strings pass through unchanged so Pydantic raises
    a clean error the caller can capture in metadata.
    """
    if not isinstance(entry, dict):
        return entry
    normalized = dict(entry)

    if "state" in normalized:
        normalized["state"] = _coerce_enum(normalized["state"], _SURFACE_STATE_VALUES, "upper")
    if "threat_class" in normalized and normalized["threat_class"] is not None:
        normalized["threat_class"] = _coerce_enum(normalized["threat_class"], _THREAT_CLASS_VALUES, "upper")
    if "defense_kind" in normalized and normalized["defense_kind"] is not None:
        normalized["defense_kind"] = _coerce_enum(normalized["defense_kind"], _DEFENSE_KIND_VALUES, "upper")
    if "confidence" in normalized:
        normalized["confidence"] = _coerce_enum(normalized["confidence"], _CONFIDENCE_VALUES, "lower")

    eps = normalized.get("backend_endpoints")
    if isinstance(eps, list):
        normalized["backend_endpoints"] = [
            {**ep, "method": _coerce_enum(ep.get("method"), _HTTP_METHOD_VALUES, "upper")}
            if isinstance(ep, dict) else ep
            for ep in eps
        ]

    # ac_overrides recurse — same enum fields apply to per-AC overrides.
    overrides = normalized.get("ac_overrides")
    if isinstance(overrides, list):
        normalized["ac_overrides"] = [
            _normalize_binding_enums(o) if isinstance(o, dict) else o
            for o in overrides
        ]

    return normalized


def _extract_raw_bindings(parsed: Any) -> tuple[List[Any], Optional[str]]:
    """Return binding dicts from LLM JSON.

    Prompt asks for ``{"bindings": [...]}`` but models often return a bare
    array of binding objects. Accept both so a valid response is not dropped.
    """
    if isinstance(parsed, dict):
        raw = parsed.get("bindings")
        if isinstance(raw, list):
            return raw, None
        return [], "dict_missing_bindings_key"
    if isinstance(parsed, list):
        return parsed, "top_level_array"
    return [], f"unexpected_root_{type(parsed).__name__}"


def _path_grounding_literals(path: str) -> List[str]:
    """Path strings that may appear in FastAPI routers or route manifest comments."""
    if not path:
        return []
    return list(dict.fromkeys([path, path.rstrip("/"), path.rstrip("/") + "/"]))


def _path_nonparam_segments(path: str) -> List[str]:
    """Non-parameter path segments, e.g. /tasks/{task_id} -> ['tasks']."""
    return [
        seg for seg in (path or "").strip("/").split("/")
        if seg and not (seg.startswith("{") and seg.endswith("}"))
    ]


def _file_grounds_endpoint(text: str, ep: BackendEndpoint) -> bool:
    """True if `text` plausibly implements the bound endpoint.

    FastAPI splits a full path across an APIRouter prefix and the route
    decorator: `APIRouter(prefix="/tasks")` + `@router.get("/{task_id}")`
    means the FULL path "/tasks/{task_id}" never appears as one literal in
    the file. So full-literal matching alone wrongly rejects every prefixed
    route — which downgraded all 6 lifecycle REQs to NEEDS_CLARIFICATION and
    produced a 0-test suite. We accept four grounding signals:
    """
    if not text:
        return False
    path = ep.path or ""

    # A) Full path literal (non-prefixed routers, route-manifest comments).
    for literal in _path_grounding_literals(path):
        if literal in text or literal.rstrip("/") in text:
            return True

    # B) Param-bearing tail — handles the prefix split. For
    #    /tasks/{task_id} the decorator literal "/{task_id}" appears in
    #    the file even though the prefix "/tasks" is declared separately.
    if "{" in path:
        segs = path.strip("/").split("/")
        for i in range(len(segs)):
            tail = "/" + "/".join(segs[i:])
            if "{" in tail and tail in text:
                return True

    # C) All non-parameter segments present — the resource noun lives in
    #    `prefix="/tasks"` and/or the decorators. For /tasks/ (list) and
    #    /tasks/{task_id} the segment "tasks" appears in the cited file.
    #    Scoped to the Resolver-cited handler_file, so coincidental matches
    #    in unrelated files are not a concern.
    nonparam = _path_nonparam_segments(path)
    if nonparam and all(seg in text for seg in nonparam):
        return True

    # D) App-wide handlers (middleware / exception handlers) — sentinel path.
    normalized = path.strip().strip("/")
    if normalized in ("", "*") and any(hint in text for hint in _NON_ROUTE_HANDLER_HINTS):
        return True
    return False


def _validate_endpoint_grounding(
    ep: BackendEndpoint,
    repo_roots: List[Path],
) -> bool:
    """Confirm the endpoint's handler_file exists and is plausibly the
    binding's defense location.

    File-level check. Accepts:
      A) FastAPI-style path literals (`/tasks/`, `/tasks/{task_id}`).
      B) Non-route handlers (middleware / exception handlers).
    """
    if not ep.handler_file or ep.handler_file.startswith("("):
        return False
    roots = [Path(r) for r in repo_roots]
    handler_candidates = [root / ep.handler_file for root in roots]
    texts: List[str] = []
    for f in handler_candidates:
        if f.is_file():
            try:
                texts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                pass
    for text in texts:
        if _file_grounds_endpoint(text, ep):
            return True
    return False


def _downgrade_low_confidence(binding: SurfaceBinding) -> SurfaceBinding:
    """Low-confidence BACKEND_API bindings get downgraded to NEEDS_CLARIFICATION.

    Reviewer's medium-issue: low confidence + claim of BACKEND_API is the
    riskiest combination — it lets a half-grounded guess drive a test pass
    that the reviewer will read as authoritative. Force the safer state.
    """
    if binding.confidence == "low" and binding.state == "BACKEND_API":
        return binding.model_copy(update={
            "state": "NEEDS_CLARIFICATION",
            "rationale": (
                "[auto-downgrade from low-confidence BACKEND_API] "
                + binding.rationale
            ),
            "backend_endpoints": [],
        })
    return binding


def _validate_threat_class(
    binding: SurfaceBinding,
    risk_owasp_ids_for_req: List[str],
) -> SurfaceBinding:
    """Enforce the DEFENSIVE_INVERTED gate (Refinement 1).

    A DEFENSIVE_INVERTED classification requires a GROUNDED backend endpoint
    (the defense must live somewhere concrete) plus a defense_assertion and a
    defense_kind (so the Generator knows the test shape).

    Downgrade rules:
      - No grounded endpoint → NOT_IMPLEMENTED (the Resolver was fabricating
        an inverted defense without code to back it).
      - Endpoint present but assertion/kind missing → keep BACKEND_API, blank
        the threat_class; Generator falls through to standard Rule 11.

    NOTE (fixed after the `validation` story bound 5/7 REQs to NOT_IMPLEMENTED):
    we DELIBERATELY do NOT require a Critic security-risk anymore. A positive
    data-validation requirement ("reject empty title with 422") has a real,
    grounded defense (the Pydantic validator) but the Critic flags NO OWASP
    risk for it — it's not a vulnerability story. Requiring a Critic risk on
    top of endpoint-grounding wrongly downgraded every such validation REQ to
    NOT_IMPLEMENTED. The endpoint-grounding check (_validate_endpoint_grounding,
    run BEFORE this) is the real anti-hallucination guard: if the cited
    endpoint isn't in the source, its endpoints are already stripped, so a
    surviving `has_endpoint` means the defense is genuinely present. The
    presence/absence of a Critic risk is recorded for telemetry only.
    """
    if binding.threat_class != "DEFENSIVE_INVERTED":
        return binding

    has_risk = bool(risk_owasp_ids_for_req)
    has_endpoint = bool(binding.backend_endpoints)
    has_assertion = bool((binding.defense_assertion or "").strip())
    has_kind = bool(binding.defense_kind)

    if not has_endpoint:
        # No grounded endpoint — the inverted defense has nowhere to live.
        return binding.model_copy(update={
            "state": "NOT_IMPLEMENTED",
            "threat_class": None,
            "anti_pattern_summary": None,
            "defense_assertion": None,
            "defense_kind": None,
            "backend_endpoints": [],
            "rationale": (
                "[auto-downgrade from DEFENSIVE_INVERTED: no grounded backend "
                "endpoint cited as defense] "
                + binding.rationale
            ),
        })

    if not has_assertion or not has_kind:
        # Endpoint and risk are there but the Generator can't write a
        # defense-confirming test without BOTH the assertion text AND the
        # kind (kind picks the status-code rule). Fall back to standard
        # Rule 11 — open generation against the endpoint, no defense
        # framing.
        missing: List[str] = []
        if not has_assertion:
            missing.append("defense_assertion")
        if not has_kind:
            missing.append("defense_kind")
        return binding.model_copy(update={
            "threat_class": None,
            "anti_pattern_summary": None,
            "defense_assertion": None,
            "defense_kind": None,
            "rationale": (
                f"[threat_class cleared: DEFENSIVE_INVERTED requires "
                f"{' and '.join(missing)}; falling back to standard binding] "
                + binding.rationale
            ),
        })

    # Grounded endpoint + assertion + kind present → keep INVERTED. Annotate
    # when there's no backing Critic risk (a positive-validation defense) so
    # the artifact is honest about why this is INVERTED without an OWASP flag.
    if not has_risk:
        return binding.model_copy(update={
            "rationale": (
                "[DEFENSIVE_INVERTED on a grounded validation defense; no Critic "
                "OWASP risk — positive data-validation, not a vulnerability] "
                + binding.rationale
            ),
        })
    return binding


# --------------------------------------------------------------------------- #
# LangGraph node                                                              #
# --------------------------------------------------------------------------- #


def _empty_chroma_map(reqs: List[ValidatedRequirement], reason: str) -> Dict[str, SurfaceBinding]:
    """Fail-loud, fail-honest: empty Chroma → every REQ is NEEDS_CLARIFICATION.

    Previously a misconfigured ingest path silently produced an empty
    context, the LLM bound everything to NOT_IMPLEMENTED, and the artifact
    looked like an honest empty suite. Now the metadata names the failure
    so the operator sees "Chroma collection empty" instead of mistaking
    it for "story has no codebase support."
    """
    return {
        r.requirement_id: SurfaceBinding(
            requirement_id=r.requirement_id,
            state="NEEDS_CLARIFICATION",
            rationale=reason,
            grounding_refs=[],
            confidence="low",
        )
        for r in reqs
    }


def _resolve_repo_roots() -> List[Path]:
    """Candidate roots for endpoint-grounding validation.

    Must include every tree that ``database.ingest`` may index. Handler paths
    from the LLM are relative to that root (e.g. ``routers/task_router.py`` for
    ``repo_cache``). Override with ``SENTINEL_REPO_ROOT`` when testing another
    checkout.
    """
    here = Path(__file__).resolve().parent.parent
    candidates: List[Path] = []
    env_root = os.getenv("SENTINEL_REPO_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend([
        here / "repo_cache",
        here,
    ])
    seen: set[Path] = set()
    roots: List[Path] = []
    for p in candidates:
        try:
            resolved = p.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots


def _apply_manual_overrides(
    surface_map: Dict[str, SurfaceBinding],
    story_id: Optional[str],
) -> Dict[str, SurfaceBinding]:
    """Apply Backend/surface_overrides/<story_id>.json if present.

    Operational hot-patch: lets a reviewer correct a mis-binding without
    redeploying. Trust-on-first-use; not for production HPE deployment
    without auth. File format: { "<req_id>": { ...SurfaceBinding fields... } }
    """
    if not story_id:
        return surface_map
    overrides_path = Path(__file__).resolve().parent.parent / "surface_overrides" / f"{story_id}.json"
    if not overrides_path.is_file():
        return surface_map
    try:
        raw = json.loads(overrides_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("surface_overrides %s unreadable: %s", overrides_path, exc)
        return surface_map
    for req_id, override in raw.items():
        try:
            surface_map[req_id] = SurfaceBinding.model_validate(override)
        except Exception as exc:  # noqa: BLE001
            logger.warning("surface_overrides %s invalid for %s: %s", overrides_path, req_id, exc)
    return surface_map


def surface_resolver_node(state: ProjectState) -> ProjectState:
    """Resolve each validated requirement to its testable surface."""

    # ---- PRE_CODE branch: derive map from DesignContracts, no LLM, no RAG --
    if state.pipeline_mode == "PRE_CODE":
        state.surface_map = _surface_map_from_design_contracts(state.design_contracts)
        state.metadata["surface_resolver_mode"] = "PRE_CODE_design_contracts"
        return state

    if not state.validated_requirements:
        state.metadata["surface_resolver_skipped"] = "no validated_requirements to bind"
        return state

    # ---- Chroma sanity check ------------------------------------------------
    try:
        coll = get_or_create_collection()
        chunk_count = coll.count()
    except Exception as exc:  # noqa: BLE001
        logger.warning("surface_resolver: Chroma access failed: %s", exc)
        state.surface_map = _empty_chroma_map(
            state.validated_requirements,
            f"Chroma collection access failed: {type(exc).__name__}: {exc}",
        )
        state.metadata["surface_resolver_error"] = "chroma_access_failed"
        return state

    state.metadata["surface_resolver_chroma_count"] = chunk_count

    if chunk_count == 0:
        state.surface_map = _empty_chroma_map(
            state.validated_requirements,
            "Chroma collection is empty — run `python -m database.ingest <root> --reset`",
        )
        state.metadata["surface_resolver_error"] = "empty_chroma_collection"
        return state

    # ---- Per-REQ union retrieval -------------------------------------------
    union_snippets, origins = _collect_union_context(state.validated_requirements)
    state.metadata["surface_resolver_retrieval"] = origins  # Generator reuses

    if not union_snippets:
        state.surface_map = _empty_chroma_map(
            state.validated_requirements,
            "Retrieval returned no snippets for any requirement.",
        )
        state.metadata["surface_resolver_error"] = "empty_retrieval"
        return state

    # ---- LLM call -----------------------------------------------------------
    llm = get_local_llm(temperature=0.0, json_mode=True)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SURFACE_RESOLVER_SYSTEM_PROMPT),
        ("user", SURFACE_RESOLVER_USER_PROMPT),
    ])
    chain = prompt | llm

    user_inputs = {
        "story_title": state.story_title or "(untitled)",
        "story_id": state.story_id or "(no story_id)",
        "user_story": state.user_story,
        "requirements_block": _render_requirements(state.validated_requirements),
        "risks_block": _render_risks(state.security_risks),
        "source_context": _render_context(union_snippets),
    }

    try:
        raw = invoke_with_retry(chain.invoke, user_inputs)
    except LLMInvocationError as exc:
        logger.error("surface_resolver: LLM invocation failed: %s", exc)
        state.surface_map = _empty_chroma_map(
            state.validated_requirements,
            f"LLM invocation failed: {exc}",
        )
        state.metadata["surface_resolver_error"] = "llm_invocation_failed"
        return state

    raw_text = stringify_response(raw)
    try:
        parsed = parse_llm_json(raw_text)
    except ValueError as exc:
        logger.error("surface_resolver: JSON parse failed: %s", exc)
        state.surface_map = _empty_chroma_map(
            state.validated_requirements,
            f"LLM output was not valid JSON: {exc}",
        )
        state.metadata["surface_resolver_error"] = "json_parse_failed"
        state.metadata["surface_resolver_raw_excerpt"] = raw_text[:2000]
        return state

    # ---- Translate to typed bindings ---------------------------------------
    # Why pre-normalization is needed:
    # The schema uses Pydantic Literal types for state, threat_class,
    # defense_kind, confidence — uppercase or specific-case spellings only.
    # LLMs (esp. Flash) often emit these in lowercase or mixed-case as
    # natural prose ("output_redaction", "Backend_Api", "Medium"). Without
    # normalization, Pydantic silently rejects the WHOLE binding and the
    # backfill kicks in with "LLM did not emit a binding" — which is what
    # killed exec-demo-search-post_code-20260530_055835 (5/5 bindings
    # silently dropped, suite_size=0). Normalize the enum-like fields
    # before model_validate, surface every rejection in metadata for
    # post-mortem.
    bindings: Dict[str, SurfaceBinding] = {}
    raw_bindings, bindings_shape = _extract_raw_bindings(parsed)
    if bindings_shape:
        state.metadata["surface_resolver_bindings_shape"] = bindings_shape
    validation_errors: List[Dict[str, str]] = []

    for entry in raw_bindings:
        if not isinstance(entry, dict):
            validation_errors.append({
                "requirement_id": "(unknown)",
                "error": f"binding entry was {type(entry).__name__}, not dict",
                "excerpt": str(entry)[:200],
            })
            continue

        req_id_for_err = str(entry.get("requirement_id") or "(unknown)")
        normalized = _normalize_binding_enums(entry)

        try:
            binding = SurfaceBinding.model_validate(normalized)
        except Exception as exc:  # noqa: BLE001
            err_str = str(exc)[:500]
            validation_errors.append({
                "requirement_id": req_id_for_err,
                "error": err_str,
                "excerpt": str(normalized)[:400],
            })
            logger.warning(
                "surface_resolver: binding dropped (validation failed) — %s: %s",
                req_id_for_err, err_str,
            )
            continue
        bindings[binding.requirement_id] = binding

    # Capture diagnostics regardless of outcome so a 0-test artifact has
    # the data to debug from.
    state.metadata["surface_resolver_raw_binding_count"] = len(raw_bindings)
    state.metadata["surface_resolver_validated_binding_count"] = len(bindings)
    if validation_errors:
        state.metadata["surface_resolver_validation_errors"] = validation_errors
    # Always store a short raw excerpt for forensic comparison.
    state.metadata["surface_resolver_raw_excerpt"] = raw_text[:2500]

    # Flag silent-empty cases. The LLM returned valid JSON but didn't
    # populate the bindings list (or populated it with only invalid
    # entries). This was the exec-demo-search-post_code-20260530_055835
    # failure mode — 5/5 REQs backfilled to NEEDS_CLARIFICATION with no
    # explanation in metadata.
    if len(raw_bindings) == 0:
        state.metadata["surface_resolver_warning"] = (
            "LLM JSON had no bindings array or it was empty. "
            "Check surface_resolver_raw_excerpt to see what was returned."
            + (f" (parse hint: {bindings_shape})" if bindings_shape else "")
        )
    elif len(bindings) == 0:
        state.metadata["surface_resolver_warning"] = (
            f"LLM emitted {len(raw_bindings)} bindings but ALL failed "
            "Pydantic validation. Check surface_resolver_validation_errors."
        )

    # ---- Backfill any REQ the LLM omitted -----------------------------------
    for req in state.validated_requirements:
        if req.requirement_id not in bindings:
            bindings[req.requirement_id] = SurfaceBinding(
                requirement_id=req.requirement_id,
                state="NEEDS_CLARIFICATION",
                rationale="LLM did not emit a binding for this requirement.",
                grounding_refs=[],
                confidence="low",
            )

    # ---- Post-validation: file grounding + low-confidence downgrade ---------
    repo_roots = _resolve_repo_roots()
    for req_id, binding in list(bindings.items()):
        if binding.state == "BACKEND_API":
            valid_eps: List[BackendEndpoint] = []
            for ep in binding.backend_endpoints:
                if _validate_endpoint_grounding(ep, repo_roots):
                    valid_eps.append(ep)
                else:
                    logger.info(
                        "surface_resolver: dropping ungrounded endpoint %s %s on %s",
                        ep.method, ep.path, ep.handler_file,
                    )
            if not valid_eps:
                # All endpoints failed grounding — downgrade to NEEDS_CLARIFICATION
                bindings[req_id] = binding.model_copy(update={
                    "state": "NEEDS_CLARIFICATION",
                    "backend_endpoints": [],
                    "rationale": (
                        "[auto-downgrade: every claimed endpoint failed file-grounding] "
                        + binding.rationale
                    ),
                })
            else:
                bindings[req_id] = binding.model_copy(update={
                    "backend_endpoints": valid_eps,
                })

    # Low-confidence BACKEND_API → NEEDS_CLARIFICATION
    bindings = {k: _downgrade_low_confidence(v) for k, v in bindings.items()}

    # Refinement 1 — DEFENSIVE_INVERTED gate. Build the per-REQ risk
    # lookup once so each binding can be checked in O(1) for whether the
    # Critic justified an inverted classification.
    risks_by_req: Dict[str, List[str]] = {}
    for risk in state.security_risks:
        for rid in (risk.affected_requirements or []):
            risks_by_req.setdefault(rid, []).append(risk.owasp_id)
    bindings = {
        k: _validate_threat_class(v, risks_by_req.get(k, []))
        for k, v in bindings.items()
    }

    # ---- Manual overrides (operational hot-patch) ---------------------------
    bindings = _apply_manual_overrides(bindings, state.story_id)

    state.surface_map = bindings
    state.metadata["surface_resolver_mode"] = "POST_CODE_resolved"
    state.metadata["surface_resolver_binding_summary"] = {
        binding.state: sum(1 for b in bindings.values() if b.state == binding.state)
        for binding in bindings.values()
    }
    # Refinement 1 telemetry — visibility into how many REQs got the
    # anti-pattern treatment. A reviewer reads this to know whether the
    # 100% resilience metric is testing real defenses (DEFENSIVE_INVERTED
    # count > 0) or just ordinary features.
    tc_summary: Dict[str, int] = {}
    inverted_defenses: List[Dict[str, str]] = []
    for b in bindings.values():
        if b.threat_class:
            tc_summary[b.threat_class] = tc_summary.get(b.threat_class, 0) + 1
        if b.threat_class == "DEFENSIVE_INVERTED" and b.defense_assertion:
            inverted_defenses.append({
                "requirement_id": b.requirement_id,
                "anti_pattern": b.anti_pattern_summary or "",
                "defense": b.defense_assertion,
            })
    if tc_summary:
        state.metadata["surface_resolver_threat_class_summary"] = tc_summary
    if inverted_defenses:
        state.metadata["surface_resolver_inverted_defenses"] = inverted_defenses
    return state
