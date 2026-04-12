"""Agent A — The Critic / Requirement Analyst.

Validates the incoming User Story for ambiguity and maps it to OWASP Top 10 risks
before any test generation happens.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from langchain_core.prompts import ChatPromptTemplate

from state import ProjectState, ValidatedRequirement, SecurityRisk
from utils import get_local_llm


CRITIC_SYSTEM_PROMPT = """You are Agent A — The Critic, a senior requirements analyst
for HPE's Sentinel-QA pipeline. You audit User Stories before any test case is written.

Your responsibilities:
1. Detect ambiguity: vague quantifiers ("fast", "secure", "some"), missing actors,
   undefined error paths, or unverifiable acceptance criteria.
2. Split compound stories into atomic, testable requirements.
3. Map each requirement to applicable OWASP Top 10 (2021) categories, with emphasis
   on injection, broken access control, and cryptographic failures for enterprise
   modules like 'Organization'.
4. Output ONLY valid JSON matching this schema:

{{
  "requirements": [
    {{
      "requirement_id": "REQ-001",
      "statement": "<atomic, testable statement>",
      "ambiguity_score": 0.0,
      "ambiguity_notes": "<null or explanation>",
      "owasp_mapping": ["A03:2021-Injection"],
      "acceptance_criteria": ["<Given/When/Then style>"]
    }}
  ],
  "risks": [
    {{
      "owasp_id": "A03:2021",
      "title": "Injection",
      "severity": "High",
      "rationale": "<why this story exposes this risk>",
      "affected_requirements": ["REQ-001"]
    }}
  ]
}}
"""


CRITIC_USER_PROMPT = """Module: {module}
User Story:
\"\"\"{user_story}\"\"\"

Analyse the story. Return JSON only — no prose, no markdown fences."""


SAMPLE_ORGANIZATION_STORY = (
    "As an HPE tenant administrator, I want to create a new Organization by "
    "submitting its legal name and primary contact email through the admin portal, "
    "so that downstream services can provision isolated resources for that tenant."
)


def _parse_response(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def critic_node(state: ProjectState) -> ProjectState:
    """LangGraph node: analyse state.user_story → populate validated_requirements + security_risks."""

    llm = get_local_llm(temperature=0.0)
    prompt = ChatPromptTemplate.from_messages(
        [("system", CRITIC_SYSTEM_PROMPT), ("user", CRITIC_USER_PROMPT)]
    )
    chain = prompt | llm
    response = chain.invoke(
        {"module": state.module or "Unknown", "user_story": state.user_story}
    )

    payload = _parse_response(response.content)

    state.validated_requirements = [
        ValidatedRequirement(**r) for r in payload.get("requirements", [])
    ]
    state.security_risks = [SecurityRisk(**r) for r in payload.get("risks", [])]
    state.metadata["critic_raw"] = response.content
    return state
