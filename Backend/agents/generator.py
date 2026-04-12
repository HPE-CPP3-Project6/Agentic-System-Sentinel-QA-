"""Agent B — The Generator / RAG Specialist.

Turns each ValidatedRequirement into concrete, executable functional TestCases.
Context is retrieved from the on-disk ChromaDB index of React + FastAPI source
so the LLM can reference real selectors, endpoints, and payload shapes.

Any requirement whose Acceptance Criterion is unverifiable (vague performance,
subjective quality, missing observable outcome) is NOT silently dropped —
it is logged to state.coverage_gaps so the pipeline surfaces the weakness.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate

from database import query_source_context
from state import (
    CoverageGap,
    ProjectState,
    TestCase,
    ValidatedRequirement,
)
from utils import get_local_llm


GENERATOR_SYSTEM_PROMPT = """You are Agent B — The Generator, a senior SDET for HPE's
Sentinel-QA pipeline. You write concrete, executable functional tests for a React
front-end backed by a FastAPI service.

Rules:
1. Produce ONE or MORE TestCases per Acceptance Criterion (AC). Every TestCase must
   trace back to exactly one AC.
2. Ground every test in the SOURCE CONTEXT provided. Prefer real selectors, route
   paths, field names, and response shapes from that context over invented ones.
3. For each test, the `coverage_rationale` must state:
     (a) which AC it satisfies, verbatim or by ID,
     (b) WHY the chosen `input_data` exercises that AC (boundary, happy-path,
         equivalence class, negative-path, etc.).
4. If an AC is UNVERIFIABLE — e.g. "system should be fast", "UI should be intuitive",
   "should be secure" without measurable threshold — DO NOT invent a test. Instead
   emit a `coverage_gaps` entry with a clear reason.
5. Output STRICT JSON. No prose, no markdown fences.

Schema:
{{
  "test_cases": [
    {{
      "test_id": "TC-<REQ-ID>-<n>",
      "title": "<short imperative>",
      "action": "<single verb phrase describing the user/system action>",
      "input_data": {{"<field>": "<value>"}},
      "expected_result": "<observable, assertable outcome>",
      "coverage_rationale": "Satisfies AC '<criterion>' of <REQ-ID>. Input chosen because ...",
      "covered_requirement_id": "<REQ-ID>",
      "covered_acceptance_criterion": "<criterion text>",
      "source_refs": ["<file or symbol from source context>"]
    }}
  ],
  "coverage_gaps": [
    {{
      "requirement_id": "<REQ-ID>",
      "acceptance_criterion": "<criterion text or null>",
      "reason": "<why this AC cannot be objectively tested>"
    }}
  ]
}}
"""


GENERATOR_USER_PROMPT = """Requirement under test:
  ID: {requirement_id}
  Statement: {statement}
  OWASP mapping: {owasp_mapping}
  Acceptance Criteria:
{acceptance_criteria_block}

Relevant source context (React + FastAPI):
----- BEGIN SOURCE CONTEXT -----
{source_context}
----- END SOURCE CONTEXT -----

Emit JSON only, following the schema exactly."""


def _format_acceptance_criteria(criteria: List[str]) -> str:
    if not criteria:
        return "  (none supplied — treat entire statement as the implicit AC)"
    return "\n".join(f"  - {c}" for c in criteria)


def _build_retrieval_query(req: ValidatedRequirement) -> str:
    ac_text = " ".join(req.acceptance_criteria)
    return f"{req.statement}\n{ac_text}".strip()


def _parse_response(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _generate_for_requirement(
    req: ValidatedRequirement,
    llm,
    n_context: int = 5,
) -> Dict[str, Any]:
    query = _build_retrieval_query(req)
    snippets = query_source_context(query, n_results=n_context)
    source_context = (
        "\n\n---\n\n".join(snippets) if snippets else "(no indexed source available)"
    )

    prompt = ChatPromptTemplate.from_messages(
        [("system", GENERATOR_SYSTEM_PROMPT), ("user", GENERATOR_USER_PROMPT)]
    )
    chain = prompt | llm
    response = chain.invoke(
        {
            "requirement_id": req.requirement_id,
            "statement": req.statement,
            "owasp_mapping": ", ".join(req.owasp_mapping) or "none",
            "acceptance_criteria_block": _format_acceptance_criteria(req.acceptance_criteria),
            "source_context": source_context,
        }
    )
    payload = _parse_response(response.content)
    payload["_raw"] = response.content
    return payload


def generator_node(state: ProjectState) -> ProjectState:
    """LangGraph node: validated_requirements → functional test_suite + coverage_gaps."""

    if not state.validated_requirements:
        state.metadata["generator_skipped"] = "no validated_requirements in state"
        return state

    llm = get_local_llm(temperature=0.1)

    new_tests: List[TestCase] = []
    new_gaps: List[CoverageGap] = []
    raw_outputs: List[str] = []

    for req in state.validated_requirements:
        try:
            payload = _generate_for_requirement(req, llm)
        except (json.JSONDecodeError, ValueError) as exc:
            new_gaps.append(
                CoverageGap(
                    requirement_id=req.requirement_id,
                    acceptance_criterion=None,
                    reason=f"Generator produced unparseable output: {exc}",
                )
            )
            continue

        raw_outputs.append(payload.pop("_raw", ""))

        for tc in payload.get("test_cases", []):
            tc.setdefault("covered_requirement_id", req.requirement_id)
            new_tests.append(TestCase(**tc))

        for gap in payload.get("coverage_gaps", []):
            gap.setdefault("requirement_id", req.requirement_id)
            new_gaps.append(CoverageGap(**gap))

    state.test_suite.extend(new_tests)
    state.coverage_gaps.extend(new_gaps)
    state.metadata["generator_raw"] = raw_outputs
    return state
