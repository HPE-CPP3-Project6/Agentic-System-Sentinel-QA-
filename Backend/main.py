"""Sentinel-QA — LangGraph entry point.

Pipeline:
    Critic  ->  Generator  ->  Red-Teamer  ->  Executor
                   ^                              |
                   |__________ heal ______________|  (conditional)
"""

from __future__ import annotations

import os

# Set Chroma home to project-local cache BEFORE importing anything that uses chromadb
_CHROMA_HOME = os.path.abspath(
    os.path.join(os.path.dirname(__file__), ".", "chroma_models_cache")
)
os.environ["CHROMA_HOME"] = _CHROMA_HOME
os.environ["HF_HOME"] = _CHROMA_HOME  # Hugging Face models cache
os.environ["ONNXRUNTIME_CACHE_DIR"] = _CHROMA_HOME  # ONNX runtime cache
os.makedirs(_CHROMA_HOME, exist_ok=True)

from langgraph.graph import StateGraph, END

from agents import (
    critic_node,
    generator_node,
    red_teamer_node,
    executor_node,
    needs_healing,
    SAMPLE_ORGANIZATION_STORY,
    SAMPLE_ORGANIZATION_ACS,
)
from state import ProjectState


def build_graph():
    graph = StateGraph(ProjectState)

    graph.add_node("critic", critic_node)
    graph.add_node("generator", generator_node)
    graph.add_node("red_teamer", red_teamer_node)
    graph.add_node("executor", executor_node)

    graph.set_entry_point("critic")
    graph.add_edge("critic", "generator")
    graph.add_edge("generator", "red_teamer")
    graph.add_edge("red_teamer", "executor")

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
