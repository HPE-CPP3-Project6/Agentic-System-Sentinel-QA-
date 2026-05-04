"""Sentinel-QA — LangGraph entry point.

Pipeline:
    Critic  ->  Generator  ->  Security+Compiler  ->  Executor
                   ^                                      |
                   |______________ heal __________________|  (conditional)
"""

from __future__ import annotations

from bootstrap import configure_caches

configure_caches()

from langgraph.graph import StateGraph, END  # noqa: E402

from agents import (  # noqa: E402
    critic_node,
    generator_node,
    security_compiler_node,
    executor_node,
    needs_healing,
)
from samples import SAMPLE_ORGANIZATION_ACS, SAMPLE_ORGANIZATION_STORY  # noqa: E402
from state import ProjectState  # noqa: E402


def build_graph():
    graph = StateGraph(ProjectState)

    graph.add_node("critic", critic_node)
    graph.add_node("generator", generator_node)
    graph.add_node("security_compiler", security_compiler_node)
    graph.add_node("executor", executor_node)

    graph.set_entry_point("critic")
    graph.add_edge("critic", "generator")
    graph.add_edge("generator", "security_compiler")
    graph.add_edge("security_compiler", "executor")

    graph.add_conditional_edges(
        "executor",
        needs_healing,
        {"heal": "generator", "end": END},
    )

    return graph.compile()


def main() -> ProjectState:
    app = build_graph()
    initial = ProjectState(
        user_story=SAMPLE_ORGANIZATION_STORY,
        acceptance_criteria=list(SAMPLE_ORGANIZATION_ACS),
        story_title="Create Organization",
        story_id="ORG-001",
        module="Organization",
    )
    return app.invoke(initial)


if __name__ == "__main__":
    final_state = main()
    print(final_state)
