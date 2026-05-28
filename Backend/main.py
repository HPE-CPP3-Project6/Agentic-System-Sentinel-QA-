"""Sentinel-QA — LangGraph entry point.

Pipeline:
    Critic  ->  Generator  ->  Security+Compiler  ->  Executor
                   ^                                      |
                   |______________ heal __________________|  (conditional)

Usage:
    python main.py                                  # default: post_code, taskshare
    python main.py --mode pre_code taskshare        # PRE_CODE: design contracts + checklist
    python main.py --mode post_code login           # full pipeline: tests + adversarial + execute
    python main.py login                            # mode defaults to post_code

POST_CODE is the original full pipeline and the default — it requires Chroma
indexed and (ideally) a live target API. PRE_CODE skips RAG and execution,
producing only DesignContracts + SecurityChecklistItems for shift-left use.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import sys
from pathlib import Path

# Windows cp1252 stdout cannot encode characters like ←/→/⚠ that downstream
# helpers (phase_bridge.persistence, _print_summary) and LLM-printed
# diagnostics use. Reconfigure BEFORE any heavy imports — without this,
# phase_bridge_error fires on a print() during POST_CODE drift load and
# drift_report ends up null (observed in exec-demo-login-post_code).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

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
from phase_bridge import generate_drift_report, load_phase1, save_phase1  # noqa: E402
from samples import SAMPLE_STORIES  # noqa: E402
from state import ProjectState  # noqa: E402


_VALID_MODES = ("pre_code", "post_code")


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


def main(story_key: str = "taskshare", mode: str = "post_code") -> ProjectState:
    app = build_graph()
    s = SAMPLE_STORIES[story_key]
    initial = ProjectState(
        user_story=s["story"],
        acceptance_criteria=s["acs"],
        story_title=s["title"],
        story_id=s["story_id"],
        module=s["module"],
        pipeline_mode=mode.upper(),
    )
    final_raw = app.invoke(initial)
    final_state = _coerce_state(final_raw)

    # --- Phase bridge integration (C1) ---
    # PRE_CODE: snapshot Critic + Generator + Security+Compiler outputs so a
    #           subsequent POST_CODE run on the same story_id can diff against
    #           "what we promised before code was written".
    # POST_CODE: if a snapshot exists for this story_id, auto-compute the
    #           drift report — the single most useful artifact the bridge
    #           produces. No separate command required.
    try:
        if final_state.pipeline_mode == "PRE_CODE":
            path = save_phase1(final_state)
            final_state.metadata["phase_bridge_saved_to"] = path
        elif final_state.pipeline_mode == "POST_CODE":
            phase1 = load_phase1(final_state.story_id or "unknown")
            if phase1:
                from state import DesignContract, SecurityChecklistItem
                if not final_state.design_contracts and "design_contracts" in phase1:
                    final_state.design_contracts.extend([
                        DesignContract(**dc) for dc in phase1["design_contracts"]
                    ])
                if not final_state.security_checklist and "security_checklist" in phase1:
                    final_state.security_checklist.extend([
                        SecurityChecklistItem(**i) for i in phase1["security_checklist"]
                    ])
                drift = generate_drift_report(phase1, final_state)
                final_state.metadata["drift_report"] = drift
            else:
                final_state.metadata["drift_report"] = {
                    "skipped": (
                        "no Phase 1 snapshot found for this story_id — run "
                        "with --mode pre_code first to enable drift reporting"
                    ),
                }
    except Exception as exc:  # noqa: BLE001 — bridge failure must not abort the run
        final_state.metadata["phase_bridge_error"] = (
            f"{type(exc).__name__}: {exc}"
        )

    return final_state


def _coerce_state(final) -> ProjectState:
    if isinstance(final, ProjectState):
        return final
    return ProjectState.model_validate(final)


def _dump_artifact(final: ProjectState, mode: str, story_key: str) -> Path:
    """Persist a JSON snapshot of the demo-relevant fields under outputs/."""
    outputs_dir = Path(__file__).resolve().parent.parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = outputs_dir / f"exec-demo-{story_key}-{mode}-{stamp}.json"

    # Strip noisy raw-LLM blobs so the artifact is human-readable
    md = {k: v for k, v in final.metadata.items() if k not in ("critic_raw", "generator_raw")}
    payload = {
        "story_id": final.story_id,
        "story_title": final.story_title,
        "pipeline_mode": final.pipeline_mode,
        "heal_attempts": final.heal_attempts,
        "validated_requirements": [r.model_dump() for r in final.validated_requirements],
        "security_risks": [r.model_dump() for r in final.security_risks],
        "design_contracts": [c.model_dump() for c in final.design_contracts],
        "security_checklist": [i.model_dump() for i in final.security_checklist],
        "test_suite_size": len(final.test_suite),
        "coverage_gaps": [g.model_dump() for g in final.coverage_gaps],
        "suggested_patches": [p.model_dump() for p in final.suggested_patches],
        "logs_summary": {
            "total": len(final.logs),
            "passed": sum(1 for l in final.logs if l.status == "passed"),
            "failed": sum(1 for l in final.logs if l.status == "failed"),
            "error": sum(1 for l in final.logs if l.status == "error"),
            "skipped": sum(1 for l in final.logs if l.status == "skipped"),
        },
        # Lifted from metadata for visibility — the drift report is one of
        # the demo-worthy artifacts on POST_CODE runs.
        "drift_report": final.metadata.get("drift_report"),
        "metadata": md,
    }
    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return target


def _print_summary(final: ProjectState, mode: str) -> None:
    print("\n" + "=" * 60)
    print(f"SENTINEL-QA  —  {mode.upper()} PIPELINE RESULTS")
    print("=" * 60)
    print(f"\nSTORY: {final.story_title} ({final.story_id})")
    print(f"Mode:  {final.pipeline_mode}")
    print(f"\nVALIDATED REQUIREMENTS ({len(final.validated_requirements)})")
    for r in final.validated_requirements:
        print(f"  - {r.requirement_id}: {r.statement[:80]}")

    if final.design_contracts:
        print(f"\nDESIGN CONTRACTS ({len(final.design_contracts)})")
        for c in final.design_contracts:
            print(f"  - {c.requirement_id}: {c.endpoint}")

    if final.security_checklist:
        print(f"\nSECURITY CHECKLIST ({len(final.security_checklist)})")
        for s in final.security_checklist:
            print(f"  - [{s.owasp_id}] {s.instruction}")

    print(f"\nTEST SUITE: {len(final.test_suite)}")
    print(f"COVERAGE GAPS: {len(final.coverage_gaps)}")
    print(f"SUGGESTED PATCHES: {len(final.suggested_patches)}   <-- headline metric")
    posture = final.metadata.get("security_posture")
    if posture:
        print(f"SECURITY POSTURE: {posture}")

    drift = final.metadata.get("drift_report")
    if drift and "summary" in drift:
        s = drift["summary"]
        print(
            f"\nDRIFT vs PHASE 1: predicted={s['predicted']} "
            f"confirmed={s['confirmed_in_phase2']} missed={s['missed_in_phase2']} "
            f"new={s['new_in_phase2_only']} exploited={s['exploited']} "
            f"checklist_ignored={s['checklist_items_ignored']}"
        )
        if drift.get("ignored_checklist_items"):
            print("  ⚠ checklist items the developer left unsatisfied:")
            for item in drift["ignored_checklist_items"][:5]:
                print(f"    - [{item['owasp_id']}] {item['instruction']}")
    elif drift and "skipped" in drift:
        print(f"\nDRIFT vs PHASE 1: {drift['skipped']}")
    elif final.pipeline_mode == "PRE_CODE":
        saved = final.metadata.get("phase_bridge_saved_to")
        if saved:
            print(f"\nPhase-1 snapshot written: {saved}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Sentinel-QA pipeline on a sample story.",
    )
    parser.add_argument(
        "story", nargs="?", default="taskshare",
        choices=list(SAMPLE_STORIES.keys()),
        help="Sample story key (default: taskshare).",
    )
    parser.add_argument(
        "--mode", choices=_VALID_MODES, default="post_code",
        help="post_code (default): full RAG + execute + heal. pre_code: design contracts + checklist only.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    final_raw = main(story_key=args.story, mode=args.mode)
    final_state = _coerce_state(final_raw)
    _print_summary(final_state, args.mode)
    artifact = _dump_artifact(final_state, args.mode, args.story)
    print(f"\nArtifact written: {artifact}")
    print("=" * 60)
