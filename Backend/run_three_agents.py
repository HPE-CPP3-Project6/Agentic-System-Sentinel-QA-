"""Smoke-run Critic → Generator → Security+Compiler (no Executor).

Materializes `workspace/runs/run_*_utc/test_sentinel_api_generated.py` when the
suite is non-empty. Requires Vertex for Critic/Generator, Chroma indexed for
RAG, and `httpx`/`Jinja2` for the compiler step.

Usage:
    python run_three_agents.py                  # default sample: filter
    python run_three_agents.py --story login      # OWASP-heavy sample (more SEC-* tests)
    SENTINEL_LOG_LEVEL=INFO python run_three_agents.py --story org
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=os.getenv("SENTINEL_LOG_LEVEL", "WARNING").upper(),
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from bootstrap import configure_caches  # noqa: E402

configure_caches()

from langgraph.graph import END, StateGraph  # noqa: E402

from agents import critic_node, generator_node, security_compiler_node  # noqa: E402
from samples import SAMPLE_STORIES  # noqa: E402
from state import ProjectState  # noqa: E402

from run_critic_generator import _print_state  # noqa: E402


def build_three_agent_graph():
    graph = StateGraph(ProjectState)
    graph.add_node("critic", critic_node)
    graph.add_node("generator", generator_node)
    graph.add_node("security_compiler", security_compiler_node)
    graph.set_entry_point("critic")
    graph.add_edge("critic", "generator")
    graph.add_edge("generator", "security_compiler")
    graph.add_edge("security_compiler", END)
    return graph.compile()


def _print_security_compiler_summary(final: ProjectState) -> None:
    print("\n" + "=" * 78)
    print("SECURITY+COMPILER (metadata)")
    print("=" * 78)
    m = final.metadata
    keys = [
        "security_compiler_adversarial_count",
        "security_compiler_workspace",
        "security_compiler_run_dir",
        "security_compiler_generated_files",
        "security_compiler_py_compile_error",
        "security_compiler_materialize_error",
        "security_compiler_skipped",
        "security_compiler_note",
        "security_compiler_unmatched_risks",
        "security_compiler_tests_truncated_to",
    ]
    printed = False
    for k in keys:
        if k in m and m[k] is not None and m[k] != []:
            print(f"{k}: {json.dumps(m[k], default=str) if not isinstance(m[k], str) else m[k]}")
            printed = True
    if not printed:
        print("(no compiler-specific metadata keys set)")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Critic → Generator → Security+Compiler on a sample story.",
    )
    parser.add_argument("--story", choices=SAMPLE_STORIES.keys(), default="filter")
    args = parser.parse_args(argv)

    sample = SAMPLE_STORIES[args.story]
    app = build_three_agent_graph()
    initial = ProjectState(
        user_story=sample["story"],
        acceptance_criteria=list(sample["acs"]),
        story_title=sample["title"],
        story_id=sample["story_id"],
        module=sample["module"],
    )

    print(
        f"Running Critic → Generator → Security+Compiler on sample '{args.story}' "
        f"({sample['story_id']} — {sample['title']})",
    )
    final = app.invoke(initial)
    final_state = (
        ProjectState.model_validate(final)
        if not isinstance(final, ProjectState)
        else final
    )
    _print_state(final_state)
    _print_security_compiler_summary(final_state)

    paths = final_state.metadata.get("security_compiler_generated_files") or []
    if paths:
        print("\nTo collect pytest only (API must be up if tests call it):")
        print(f"  pytest \"{paths[0]}\" --collect-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
