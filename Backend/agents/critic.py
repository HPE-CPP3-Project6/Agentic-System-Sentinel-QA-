"""Agent A — The Critic / Requirement Analyst.

Consumes a User Story together with its author-provided Acceptance Criteria,
audits each AC for ambiguity and testability, and maps to OWASP Top 10 only
where the risk is genuine (no force-fitting security tags onto purely
functional requirements).
"""

from __future__ import annotations

from typing import List

from langchain_core.prompts import ChatPromptTemplate

from state import ProjectState, ValidatedRequirement, SecurityRisk
from utils import get_local_llm, parse_llm_json


CRITIC_SYSTEM_PROMPT = """You are Agent A — The Critic, a senior requirements analyst
for HPE's Sentinel-QA pipeline. You audit User Stories and their author-provided
Acceptance Criteria BEFORE any test case is written.

Ground rules:
1. Treat each supplied Acceptance Criterion as the primary unit of requirement.
   Produce exactly one ValidatedRequirement per AC, preserving the original
   statement in `statement`. If an AC is compound (contains "and"/"or" joining
   two independently testable behaviours), split it and suffix the id (e.g.
   REQ-003a, REQ-003b). When you split, REWRITE each half as a complete
   standalone sentence — never emit a grammatical fragment that begins with
   "and", "or", or a dangling clause. Bad: "and persist the contact email."
   Good: "The API must persist the contact email on success."
2. Score ambiguity in [0.0, 1.0]:
     0.0  — fully unambiguous, deterministically testable.
     0.3  — minor gap (missing edge case, implicit default).
     0.6  — vague quantifier / undefined term ("fast", "clean", "immediately").
     0.9+ — unverifiable or contradicts another AC.
   Put the reason in `ambiguity_notes` whenever score > 0.0, else null.
3. For every AC emit 1–3 concrete Given/When/Then style acceptance_criteria
   entries that a test generator can turn into executable steps.
4. OWASP mapping is STRICT. Tag a requirement only when the AC itself names
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
   a tag pollutes the downstream Red-Teamer with irrelevant payloads.
5. The top-level `risks` array aggregates distinct OWASP categories that apply
   to this story. If none apply, return an empty list. Severity must be one of
   "Low" | "Medium" | "High" | "Critical" and reflect real blast radius
   (a filter bypass that reveals other tenants' data is High; a sort default
   regression is Low).

Output ONLY valid JSON — no markdown fences, no commentary — matching:

{{
  "requirements": [
    {{
      "requirement_id": "REQ-001",
      "statement": "<original or atomic split of the AC>",
      "ambiguity_score": 0.0,
      "ambiguity_notes": null,
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


SAMPLE_ORGANIZATION_STORY = (
    "As an HPE tenant administrator, I want to create a new Organization by "
    "submitting its legal name and primary contact email through the admin portal, "
    "so that downstream services can provision isolated resources for that tenant."
)

SAMPLE_ORGANIZATION_ACS: List[str] = [
    "The legal name field must reject empty strings and strings longer than 255 characters.",
    "Submitting a duplicate legal name must return a 409 Conflict without creating a record.",
    "On success the API must return the new organization_id and persist the contact email.",
]


# Example from the task-manager spec — used for smoke-testing the Critic on
# functional stories where OWASP mapping should remain mostly empty.
SAMPLE_FILTER_STORY = (
    "As a user, I want to filter my tasks by priority so that I can focus on "
    "high-priority items first."
)
SAMPLE_FILTER_ACS: List[str] = [
    "The filter dropdown must contain: All, Low, Medium, High.",
    "Selecting 'High' must hide all Low and Medium priority tasks immediately.",
    "Selecting 'All' must reset the view to show all tasks regardless of priority.",
]


def _format_acceptance_block(acs: List[str]) -> str:
    if not acs:
        return "(none provided — infer reasonable ACs from the story)"
    return "\n".join(f"  AC{i+1}: {ac}" for i, ac in enumerate(acs))


def critic_node(state: ProjectState) -> ProjectState:
    """LangGraph node: audit user_story + acceptance_criteria → validated_requirements + security_risks."""

    llm = get_local_llm(temperature=0.0, json_mode=True)
    prompt = ChatPromptTemplate.from_messages(
        [("system", CRITIC_SYSTEM_PROMPT), ("user", CRITIC_USER_PROMPT)]
    )
    chain = prompt | llm
    response = chain.invoke(
        {
            "module": state.module or "Unknown",
            "story_id": state.story_id or "N/A",
            "story_title": state.story_title or "N/A",
            "user_story": state.user_story,
            "acceptance_block": _format_acceptance_block(state.acceptance_criteria),
        }
    )

    payload = parse_llm_json(response.content)

    state.validated_requirements = [
        ValidatedRequirement(**r) for r in payload.get("requirements", [])
    ]
    state.security_risks = [SecurityRisk(**r) for r in payload.get("risks", [])]
    state.metadata["critic_raw"] = response.content
    return state
