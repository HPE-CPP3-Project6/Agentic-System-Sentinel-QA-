"""Smoke-run the first two Sentinel-QA agents end-to-end.

Runs Critic → Generator on one of the bundled sample stories and pretty-prints
the resulting ProjectState: validated requirements, security risks, test
suite, and any coverage gaps.

Usage:
    python run_critic_generator.py                # defaults to the filter story
    python run_critic_generator.py --story org    # organization / A03 sample
    python run_critic_generator.py --n-context 8  # retrieve more RAG snippets
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from langgraph.graph import StateGraph, END

from agents import (
    critic_node,
    generator_node,
    SAMPLE_FILTER_ACS,
    SAMPLE_FILTER_STORY,
    SAMPLE_ORGANIZATION_ACS,
    SAMPLE_ORGANIZATION_STORY,
)
from state import ProjectState


SAMPLES = {
    "filter": {
        "story": SAMPLE_FILTER_STORY,
        "acs": SAMPLE_FILTER_ACS,
        "title": "Filter by Priority",
        "story_id": "US-001",
        "module": "TaskManager",
    },
    "org": {
        "story": SAMPLE_ORGANIZATION_STORY,
        "acs": SAMPLE_ORGANIZATION_ACS,
        "title": "Create Organization",
        "story_id": "ORG-001",
        "module": "Organization",
    },
}


def build_two_agent_graph():
    graph = StateGraph(ProjectState)
    graph.add_node("critic", critic_node)
    graph.add_node("generator", generator_node)
    graph.set_entry_point("critic")
    graph.add_edge("critic", "generator")
    graph.add_edge("generator", END)
    return graph.compile()


def _print_header(label: str) -> None:
    print("\n" + "=" * 78)
    print(label)
    print("=" * 78)


def _print_state(final: ProjectState) -> None:
    _print_header("VALIDATED REQUIREMENTS")
    for r in final.validated_requirements:
        print(f"- [{r.requirement_id}] ambiguity={r.ambiguity_score:.2f} "
              f"owasp={r.owasp_mapping or '[]'}")
        print(f"    {r.statement}")
        if r.ambiguity_notes:
            print(f"    ! {r.ambiguity_notes}")
        for ac in r.acceptance_criteria:
            print(f"      · {ac}")

    _print_header("SECURITY RISKS (from Critic)")
    if not final.security_risks:
        print("(none — Critic did not flag any OWASP exposure)")
    for risk in final.security_risks:
        print(f"- {risk.owasp_id} {risk.title} [{risk.severity}] "
              f"→ {risk.affected_requirements}")
        print(f"    {risk.rationale}")

    _print_header("TEST SUITE (from Generator)")
    for tc in final.test_suite:
        print(f"- [{tc.test_id}] {tc.title}")
        print(f"    action: {tc.action}")
        print(f"    input : {json.dumps(tc.input_data, default=str)}")
        print(f"    expect: {tc.expected_result}")
        print(f"    refs  : {tc.source_refs}")
        print(f"    why   : {tc.coverage_rationale}")

    _print_header("COVERAGE GAPS")
    if not final.coverage_gaps:
        print("(none)")
    for g in final.coverage_gaps:
        print(f"- {g.requirement_id} :: {g.acceptance_criterion or '—'}")
        print(f"    {g.reason}")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Critic → Generator on a sample story.")
    parser.add_argument("--story", choices=SAMPLES.keys(), default="filter")
    parser.add_argument("--n-context", type=int, default=5,
                        help="(reserved) number of RAG snippets to retrieve.")
    args = parser.parse_args(argv)

    sample = SAMPLES[args.story]
    app = build_two_agent_graph()

    initial = ProjectState(
        user_story=sample["story"],
        acceptance_criteria=list(sample["acs"]),
        story_title=sample["title"],
        story_id=sample["story_id"],
        module=sample["module"],
    )

    print(f"Running Critic → Generator on sample '{args.story}' "
          f"({sample['story_id']} — {sample['title']})")
    final = app.invoke(initial)
    # LangGraph returns a dict-like; rehydrate for typed access.
    final_state = ProjectState.model_validate(final) if not isinstance(final, ProjectState) else final
    _print_state(final_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
