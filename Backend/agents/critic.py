"""Agent A — The Critic / Requirement Analyst.

Consumes a User Story together with its author-provided Acceptance Criteria,
audits each AC for ambiguity and testability, and maps to OWASP Top 10 only
where the risk is genuine (no force-fitting security tags onto purely
functional requirements).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate

from config import get_settings
from state import ProjectState, SecurityRisk, ValidatedRequirement
from utils import (
    LLMInvocationError,
    get_local_llm,
    invoke_with_retry,
    parse_llm_json,
    stringify_response,
)

logger = logging.getLogger(__name__)


CRITIC_SYSTEM_PROMPT = """You are Agent A — The Critic, a senior requirements analyst
for HPE's Sentinel-QA pipeline. You audit User Stories and their author-provided
Acceptance Criteria BEFORE any test case is written. Your job is to be BRUTALLY HONEST.

Ground rules:
1. Treat each supplied Acceptance Criterion as the primary unit of requirement.
   Produce exactly one ValidatedRequirement per AC, preserving the original
   statement in `statement`. If an AC is compound (contains "and"/"or" joining
   two independently testable behaviours), split it and suffix the id (e.g.
   REQ-003a, REQ-003b). When you split, REWRITE each half as a complete
   standalone sentence — never emit a grammatical fragment that begins with
   "and", "or", or a dangling clause. Bad: "and persist the contact email."
   Good: "The API must persist the contact email on success."

2. AMBIGUITY AUDIT (Be Brutal):
   Score ambiguity in [0.0, 1.0]:
     0.0  — fully unambiguous, deterministically testable, measurable.
     0.3  — minor gap (missing edge case, implicit default).
     0.6+ — PENALIZE heavily: contains non-quantifiable adjectives like:
            "intuitive", "fast", "smooth", "modern", "clean", "secure",
            "user-friendly", "responsive", "elegant", "robust", "efficient".
            If you cannot measure it with a stopwatch or a boolean, score >= 0.6.
     0.9+ — unverifiable, contradicts another AC, or purely aspirational.
   
   Put the reason in `ambiguity_notes` ALWAYS when score > 0.0. Call out the
   problematic word explicitly: e.g., "Uses vague adjective 'intuitive' (not measurable)."
   
3. SEVERITY SCORING (1–10 scale):
   Score based on IMPACT × EXPLOITABILITY:
   
   10 = CRITICAL
     - Plaintext token transmission (A04 but extreme impact)
     - Unlimited brute force without lockout (A04)
     - SQL injection in login (A03)
     - Broken access control allowing data theft (A01)
   
   8–9 = HIGH
     - Rate limiting missing but not on login (A04)
     - User enumeration via error messages (A07)
     - Unencrypted sensitive data on page (A04)
     - Reflected XSS in search (A03)
   
   5–7 = MEDIUM
     - Input validation issues on non-critical fields
     - Missing pagination (DoS potential but low)
     - Verbose error messages (info disclosure)
   
   1–4 = LOW
     - Cosmetic UI bugs
     - Typos in labels
     - Missing nice-to-have features
   
   Put rationale in `severity_rationale`: e.g., "Plaintext token + HTTP = immediate
   session hijacking. Impact: account compromise. Exploitability: trivial (network
   sniffer). Score: 10."

4. DEPENDENCY MAPPING:
   Identify requirements that depend on other requirements. Examples:
     - "User can search tasks" depends on "User can log in"
     - "Task notification sent" depends on "Task created"
     - "Dashboard displays user profile" depends on "User logged in"
   
   Add these dependencies as a list of requirement IDs. Examples:
     dependencies: ["REQ-001"]  # This AC depends on login (REQ-001)
     dependencies: []           # No dependencies

5. For every AC emit 1–3 concrete Given/When/Then style acceptance_criteria
   entries that a test generator can turn into executable steps.

6. OWASP mapping is STRICT. Tag a requirement only when the AC itself names
   a concrete attack surface — evidence must be visible IN the AC text, not
   inferred from "this input might one day reach a database":
     - A01 Broken Access Control — the AC explicitly concerns cross-tenant
       or cross-user data visibility, privilege elevation, or authZ checks.
     - A03 Injection — the AC describes a value flowing into a query,
       command, template, or other interpreter (e.g., a search string that
       filters DB rows, a filter value templated into SQL, user HTML that
       renders in the DOM). Bare input validation, length limits, format
       checks, and plain persistence DO NOT qualify.
     - A04 Insecure Design — a required SECURITY CONTROL is missing by
       design: rate limiting, MFA, step-up auth, session binding, etc.
       Data-constraint violations (duplicate checks, length bounds,
       uniqueness) are FUNCTIONAL requirements, not A04.
     - A08 Software & Data Integrity — integrity verification of signed or
       serialised data, software updates, or CI/CD artifacts. Plain uniqueness
       constraints or business-rule enforcement DO NOT qualify.

   Hard filter: if the only justification you can write contains the word
   "could", "might", or "may be", you are speculating — DROP the mapping.
   Prefer `"owasp_mapping": []` with empty `risks` over a weak tag. Forcing
   a tag pollutes the downstream Security+Compiler agent with irrelevant payloads.

7. The top-level `risks` array aggregates distinct OWASP categories that apply
   to this story. If none apply, return an empty list. Severity must be one of
   "Low" | "Medium" | "High" | "Critical" and reflect real blast radius
   (a plaintext token is Critical; a sort default regression is Low).

Output ONLY valid JSON — no markdown fences, no commentary — matching:

{{
  "requirements": [
    {{
      "requirement_id": "REQ-001",
      "statement": "<original or atomic split of the AC>",
      "ambiguity_score": 0.0,
      "ambiguity_notes": null,
      "severity_score": 5,
      "severity_rationale": "<why this severity>",
      "dependencies": [],
      "owasp_mapping": [],
      "acceptance_criteria": ["Given ..., When ..., Then ..."]
    }}
  ],
  "risks": [
    {{
      "owasp_id": "A03:2021",
      "title": "Injection",
      "severity": "Medium",
      "rationale": "<why THIS story exposes this risk>",
      "affected_requirements": ["REQ-001"]
    }}
  ]
}}
"""


CRITIC_USER_PROMPT = """Module: {module}
Story ID: {story_id}
Story Title: {story_title}

User Story:
\"\"\"{user_story}\"\"\"

Author-provided Acceptance Criteria:
{acceptance_block}

Audit the story. Return JSON only."""


def _format_acceptance_block(acs: List[str]) -> str:
    if not acs:
        return "(none provided — infer reasonable ACs from the story)"
    return "\n".join(f"  AC{i+1}: {ac}" for i, ac in enumerate(acs))


def _safe_models(
    raw_list: List[Dict[str, Any]],
    model_cls: type,
    label: str,
) -> tuple[List[Any], List[Dict[str, Any]]]:
    """Parse LLM rows into Pydantic models; skip bad rows instead of failing the whole node."""
    good: List[Any] = []
    skipped: List[Dict[str, Any]] = []
    for row in raw_list:
        if not isinstance(row, dict):
            skipped.append({"row": row, "error": f"{label}: expected object, got {type(row).__name__}"})
            continue
        try:
            good.append(model_cls(**row))
        except Exception as exc:  # noqa: BLE001 — LLM output is untrusted
            skipped.append({"row": row, "error": f"{label}: {exc}"})
    return good, skipped


def critic_node(state: ProjectState) -> ProjectState:
    """LangGraph node: audit user_story + acceptance_criteria → validated_requirements + security_risks.
    
    Can be customized via environment variables:
    - SENTINEL_LLM_MODEL: model name (e.g., "gemini-3.1-pro-preview")
    - VERTEX_AI_LOCATION: location (e.g., "global" for Gemini 3.1)
    """
    import time as _t

    _t0 = _t.perf_counter()
    logger.info("[critic] invoking Vertex (Gemini) …")

    llm = get_local_llm(
        temperature=0.0,
        json_mode=True,
        model=get_settings().sentinel_llm_model,  # centralized config
        location=get_settings().vertex_ai_location,  # centralized config
        seed=42,
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", CRITIC_SYSTEM_PROMPT), ("user", CRITIC_USER_PROMPT)]
    )
    chain = prompt | llm
    invoke_ctx = {
        "module": state.module or "Unknown",
        "story_id": state.story_id or "N/A",
        "story_title": state.story_title or "N/A",
        "user_story": state.user_story,
        "acceptance_block": _format_acceptance_block(state.acceptance_criteria),
    }
    try:
        response = invoke_with_retry(chain.invoke, invoke_ctx)
    except LLMInvocationError as exc:
        logger.error("[critic] Vertex failed after retries: %s", exc)
        state.metadata["critic_error"] = str(exc)
        state.metadata["critic_error_cause"] = f"{type(exc.cause).__name__}: {exc.cause}"
        return state

    logger.info("[critic] Vertex returned in %.1fs", _t.perf_counter() - _t0)

    try:
        payload = parse_llm_json(response.content)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("[critic] Failed to parse Critic JSON: %s", exc)
        # Return with empty requirements and risks if parsing fails
        state.metadata["critic_error"] = str(exc)
        state.metadata["critic_raw"] = stringify_response(response.content)
        return state

    req_raw = payload.get("requirements", [])
    risk_raw = payload.get("risks", [])
    if not isinstance(req_raw, list):
        req_raw = []
    if not isinstance(risk_raw, list):
        risk_raw = []

    reqs, skipped_req = _safe_models(req_raw, ValidatedRequirement, "ValidatedRequirement")
    risks, skipped_risk = _safe_models(risk_raw, SecurityRisk, "SecurityRisk")

    state.validated_requirements = reqs
    state.security_risks = risks
    state.metadata["critic_raw"] = stringify_response(response.content)
    if skipped_req or skipped_risk:
        state.metadata["critic_skipped_rows"] = {
            "requirements": skipped_req,
            "risks": skipped_risk,
        }
    return state
