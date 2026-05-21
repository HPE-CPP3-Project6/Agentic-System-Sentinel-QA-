"""Sentinel-QA — LangGraph entry point.

Pipeline:
    Critic  ->  Generator  ->  Security+Compiler  ->  Executor
                   ^                                      |
                   |______________ heal __________________|  (conditional)

Usage:
    python main.py              # runs default story (taskshare)
    python main.py login        # runs login story
    python main.py perms        # runs permissions story
    python main.py search       # runs search/injection story
    python main.py taskshare    # runs IDOR task share story
"""

from __future__ import annotations

import sys

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
from samples import SAMPLE_STORIES  # noqa: E402
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


def main(story_key: str = "taskshare") -> ProjectState:
    app = build_graph()
    s = SAMPLE_STORIES[story_key]
    initial = ProjectState(
        user_story=s["story"],
        acceptance_criteria=s["acs"],
        story_title=s["title"],
        story_id=s["story_id"],
        module=s["module"],
        pipeline_mode="PRE_CODE",
    )
    return app.invoke(initial)


if __name__ == "__main__":
    key = sys.argv[1] if len(sys.argv) > 1 else "taskshare"
    final_state = main(story_key=key)

    print("\n" + "="*60)
    print("SENTINEL-QA  —  PRE_CODE PIPELINE RESULTS")
    print("="*60)

    print(f"\n📋 STORY: {final_state['story_title']} ({final_state['story_id']})")
    print(f"🔧 Mode:  {final_state['pipeline_mode']}")

    print(f"\n✅ VALIDATED REQUIREMENTS ({len(final_state['validated_requirements'])})")
    for r in final_state['validated_requirements']:
        print(f"  • {r.requirement_id}: {r.statement[:80]}...")

    print(f"\n📄 DESIGN CONTRACTS ({len(final_state['design_contracts'])})")
    for c in final_state['design_contracts']:
        print(f"  • {c.requirement_id}: {c.endpoint}")
        if c.validation_rules:
            for rule in c.validation_rules:
                print(f"      - {rule}")

    print(f"\n🔒 SECURITY CHECKLIST ({len(final_state['security_checklist'])})")
    for s in final_state['security_checklist']:
        print(f"  • [{s.owasp_id}] {s.instruction}")

    print(f"\n🧪 TEST SUITE: {len(final_state['test_suite'])} tests (expected 0 in PRE_CODE)")

    print("\n📊 METADATA")
    for k, v in final_state['metadata'].items():
        if k not in ('critic_raw', 'generator_raw'):
            print(f"  • {k}: {v}")

    print("\n" + "="*60)