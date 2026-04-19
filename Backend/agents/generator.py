"""Agent B — The Generator / RAG Specialist.

Turns each ValidatedRequirement into concrete, executable functional TestCases,
grounded in real snippets retrieved from the on-disk ChromaDB index of the
React + FastAPI source tree.

Design points:
- One retrieval per requirement (the Critic already splits compound ACs, so
  each ValidatedRequirement is one atomic testable unit).
- Snippets are injected WITH their `path:start-end` header so the model can
  cite real locations in `source_refs`. Retrieved paths are also used as a
  fallback when the model omits `source_refs`.
- Unverifiable ACs are NOT silently dropped — they land in `coverage_gaps`.
- Test IDs are stamped by the node to guarantee uniqueness across requirements.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.prompts import ChatPromptTemplate

from database import SourceSnippet, query_source_snippets
from state import (
    CoverageGap,
    ProjectState,
    TestCase,
    ValidatedRequirement,
)
from utils import get_local_llm, parse_llm_json


GENERATOR_SYSTEM_PROMPT = """You are Agent B — The Generator, a senior SDET for HPE's
Sentinel-QA pipeline. You write concrete, executable functional tests for a React
front-end backed by a FastAPI service.

Rules:
1. Produce ONE or MORE TestCases per Acceptance Criterion (AC). Every TestCase
   must trace back to exactly one AC via `covered_requirement_id` and
   `covered_acceptance_criterion`.
2. GROUND every test in the SOURCE CONTEXT provided. Prefer real selectors,
   route paths, field names, and response shapes found there over invented
   ones. Populate `source_refs` with the `path:start-end` headers of the
   snippets you actually relied on. If no snippet was useful, return an empty
   list — do NOT fabricate paths.
3. Cover at minimum: the happy path, one boundary/equivalence case, and one
   negative path per AC WHERE THE AC ADMITS THEM. If the AC is a pure
   enumeration ("dropdown must contain X, Y, Z") one assertion-style test is
   sufficient.
4. `coverage_rationale` MUST state:
     (a) which AC it satisfies (verbatim or by ID),
     (b) WHY the chosen `input_data` exercises that AC — boundary value,
         equivalence class, negative path, state-transition, etc.
5. If an AC is UNVERIFIABLE — vague ("fast", "intuitive", "secure") with no
   measurable threshold, or missing an observable outcome — DO NOT invent a
   test. Emit a `coverage_gaps` entry explaining why.
6. Output STRICT JSON. No prose, no markdown fences, no trailing commentary.

Schema:
{{
  "test_cases": [
    {{
      "title": "<short imperative>",
      "action": "<single verb phrase: 'select High from priority filter'>",
      "input_data": {{"<field>": "<value>"}},
      "expected_result": "<observable, assertable outcome>",
      "coverage_rationale": "Satisfies AC '<criterion>' of <REQ-ID>. Input chosen because ...",
      "covered_requirement_id": "<REQ-ID>",
      "covered_acceptance_criterion": "<criterion text>",
      "source_refs": ["<path:start-end from source context>"]
    }}
  ],
  "coverage_gaps": [
    {{
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


def _snippet_header(s: SourceSnippet) -> str:
    return f"{s.path}:{s.start_line}-{s.end_line}"


def _generate_for_requirement(
    req: ValidatedRequirement,
    llm,
    n_context: int = 5,
) -> tuple[Dict[str, Any], List[SourceSnippet]]:
    query = _build_retrieval_query(req)
    snippets = query_source_snippets(query, n_results=n_context)
    source_context = (
        "\n\n---\n\n".join(s.as_prompt_block() for s in snippets)
        if snippets
        else "(no indexed source available — generate against the requirement alone)"
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
    payload = parse_llm_json(response.content)
    payload["_raw"] = response.content
    return payload, snippets


def generator_node(state: ProjectState) -> ProjectState:
    """LangGraph node: validated_requirements → functional test_suite + coverage_gaps."""

    if not state.validated_requirements:
        state.metadata["generator_skipped"] = "no validated_requirements in state"
        return state

    llm = get_local_llm(temperature=0.1, json_mode=True)

    new_tests: List[TestCase] = []
    new_gaps: List[CoverageGap] = []
    raw_outputs: List[str] = []

    for req in state.validated_requirements:
        try:
            payload, snippets = _generate_for_requirement(req, llm)
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
        retrieved_refs = [_snippet_header(s) for s in snippets]

        for idx, tc in enumerate(payload.get("test_cases", []), start=1):
            tc.setdefault("covered_requirement_id", req.requirement_id)
            tc["test_id"] = f"TC-{req.requirement_id}-{idx:02d}"
            if not tc.get("source_refs") and retrieved_refs:
                tc["source_refs"] = retrieved_refs[:2]
            new_tests.append(TestCase(**tc))

        for gap in payload.get("coverage_gaps", []):
            gap.setdefault("requirement_id", req.requirement_id)
            new_gaps.append(CoverageGap(**gap))

    state.test_suite.extend(new_tests)
    state.coverage_gaps.extend(new_gaps)
    state.metadata["generator_raw"] = raw_outputs
    return state
