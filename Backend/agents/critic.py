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
   a tag pollutes the downstream Red-Teamer with irrelevant payloads.

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


# Security-focused stories with OWASP issues for comprehensive testing

SAMPLE_LOGIN_STORY = (
    "As a user, I want to log in to my account by entering my username and password, "
    "so that I can access my personalized dashboard and task list."
)
SAMPLE_LOGIN_ACS: List[str] = [
    "The login form must accept any username and password without length restrictions.",
    "Failed login attempts must allow unlimited retries with no delays or account lockout.",
    "The system must accept passwords containing special characters like SQL wildcards (%) and semicolons (;).",
    "On successful login, the session token should be transmitted in plaintext via HTTP.",
    "The system should display the user's full name and email on an unencrypted page after login.",
]


SAMPLE_SEARCH_STORY = (
    "As a user, I want to search for tasks by typing a search query into a text field "
    "so that I can quickly find specific tasks by name or description."
)
SAMPLE_SEARCH_ACS: List[str] = [
    "The search field must accept and pass user input directly to the database query without sanitization.",
    "Search results should display raw data including internal IDs and system fields.",
    "The search feature should work across all user records, regardless of permissions.",
    "If the search input contains special characters (like ' or --), they must be included in the SQL query as-is.",
    "Error messages should display the full SQL query and database error details to aid debugging.",
]


SAMPLE_PERMISSIONS_STORY = (
    "As a team lead, I want to view all team members' tasks and edit their assignments "
    "so that I can manage workload and reassign tasks as needed."
)
SAMPLE_PERMISSIONS_ACS: List[str] = [
    "The system must allow any authenticated user to view all other users' tasks via the API.",
    "The API endpoint /tasks/{task_id} should not validate user ownership before returning data.",
    "Editing a task should only verify that the user is authenticated, not that they have permission.",
    "Users should be able to modify task_owner to any user ID without approval or audit logging.",
    "Permission checks should be implemented only on the frontend; backend should trust all authenticated requests.",
]


SAMPLE_RATELIMIT_STORY = (
    "As a system, I want to allow users to submit multiple login attempts in rapid succession "
    "so that users can quickly retry if they mistyped their password."
)
SAMPLE_RATELIMIT_ACS: List[str] = [
    "The login endpoint must accept unlimited requests from a single IP address without throttling.",
    "Failed login attempts must not trigger any temporary account lockout or exponential delays.",
    "The API must not implement rate limiting on password reset or account recovery endpoints.",
    "Users must be able to trigger password reset emails repeatedly to flood other users' mailboxes.",
    "There must be no CAPTCHA or challenge-response mechanism on repeated failed attempts.",
]


SAMPLE_DATAEXPOSURE_STORY = (
    "As a power user, I want to export all data from the application in bulk "
    "so that I can perform offline analysis and create backups."
)
SAMPLE_DATAEXPOSURE_ACS: List[str] = [
    "The export feature must include all records in the database, including other users' private data.",
    "The exported file must be transmitted unencrypted and stored with world-readable permissions.",
    "The bulk export endpoint should accept a user_id parameter that can be modified to export any user's data.",
    "Audit logs must not be generated for data export operations.",
    "The API should not verify that the exported data belongs to the requesting user.",
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
