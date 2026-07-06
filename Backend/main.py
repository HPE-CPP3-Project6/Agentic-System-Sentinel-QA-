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
import os
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
    surface_resolver_node,
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
    graph.add_node("surface_resolver", surface_resolver_node)
    graph.add_node("generator", generator_node)
    graph.add_node("security_compiler", security_compiler_node)
    graph.add_node("executor", executor_node)

    graph.set_entry_point("critic")
    # Layer A — Surface Resolver between Critic and Generator. Produces
    # state.surface_map, the typed binding every downstream agent consults.
    graph.add_edge("critic", "surface_resolver")
    graph.add_edge("surface_resolver", "generator")
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
    # Demo/CI knob — cap heal cycles. The heal loop re-embeds RAG context on
    # CPU per failing test, so a large suite can take 15-40 min. Set
    # SENTINEL_MAX_HEAL=1 (or 0) for fast demo/smoke runs. Default unchanged (2).
    _max_heal = os.getenv("SENTINEL_MAX_HEAL")
    if _max_heal is not None:
        try:
            initial.max_heal_attempts = max(0, int(_max_heal))
        except ValueError:
            pass
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
                # Stage 4 (Cursor merged priority list) — auto-seed a phase1
                # snapshot from this POST_CODE run so the NEXT run can drift
                # against it.
                # Background: in the prior version, a story that had only
                # ever been run in POST_CODE produced "skipped" drift on
                # every single run, forever. Users had to remember to run
                # --mode pre_code once, manually, which never happened in
                # practice (observed: 4/5 demo stories had null drift_report).
                # Now: the first POST_CODE run seeds the snapshot from
                # whatever PRE_CODE-shaped fields exist on the state
                # (security_risks + validated_requirements are populated by
                # the Critic in BOTH modes; design_contracts and
                # security_checklist will be empty in POST_CODE, which is
                # fine — drift_report tolerates empty inputs and the
                # second run will diff predicted-vs-exploited risks).
                seed_path = save_phase1(final_state)
                final_state.metadata["phase_bridge_seeded_from_post_code"] = seed_path
                final_state.metadata["drift_report"] = {
                    "skipped": (
                        "no Phase 1 snapshot existed — seeded one from this "
                        "POST_CODE run; rerun the same story to see drift"
                    ),
                    "seeded_snapshot_path": seed_path,
                }
    except Exception as exc:  # noqa: BLE001 — bridge failure must not abort the run
        final_state.metadata["phase_bridge_error"] = (
            f"{type(exc).__name__}: {exc}"
        )

    # --- SAST sidecar (Phase 3A) ---
    # Static analysis of the target source, in a SEPARATE bucket. The dynamic
    # pipeline tested the running app; Bandit reads the source. Never merged
    # into security_posture, never healed. Disable with SENTINEL_SAST=0.
    if (
        final_state.pipeline_mode == "POST_CODE"
        and os.getenv("SENTINEL_SAST", "1").strip().lower() not in ("0", "false", "no")
    ):
        try:
            from tools.sast_scan import run_sast_scan
            target_root = Path(__file__).resolve().parent / "repo_cache"
            final_state.metadata["sast_summary"] = run_sast_scan(target_root)
        except Exception as exc:  # noqa: BLE001 — sidecar must not abort the run
            final_state.metadata["sast_summary"] = {
                "tool": "bandit", "ran": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }

    return final_state


def _coerce_state(final) -> ProjectState:
    if isinstance(final, ProjectState):
        return final
    return ProjectState.model_validate(final)


def _dump_artifact(final: ProjectState, mode: str, story_key: str) -> Path:
    """Persist a JSON snapshot under outputs/.

    Uses the shim's `state_to_artifact` as the single source of truth for the
    artifact envelope (security_posture, resilience_pct, joined execution_logs,
    test_suite, attestation fields), then overlays the CLI-only extras.
    Previously this function maintained its own envelope, which drifted from
    the shim's — every CLI artifact had resilience_pct/security_posture
    missing while the browser showed them fine.
    """
    from shim.artifact import state_to_artifact

    outputs_dir = Path(__file__).resolve().parent.parent / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = outputs_dir / f"exec-demo-{story_key}-{mode}-{stamp}.json"

    payload = state_to_artifact(final)

    # CLI-only extras the shim envelope doesn't carry.
    final_attempt = final.heal_attempts
    current_cycle_logs = [
        l for l in final.logs if l.heal_attempt == final_attempt
    ] if final_attempt > 0 else list(final.logs)
    payload.update(
        {
            "heal_attempts": final.heal_attempts,
            "validated_requirements": [r.model_dump() for r in final.validated_requirements],
            "security_risks": [r.model_dump() for r in final.security_risks],
            "test_suite_size": len(final.test_suite),
            "coverage_gaps": [g.model_dump() for g in final.coverage_gaps],
            "logs_summary": {
                # Scoped to the final heal cycle so headline numbers mean
                # "current posture", not a sum across heal cycles.
                "heal_attempt": final_attempt,
                "total": len(current_cycle_logs),
                "passed": sum(1 for l in current_cycle_logs if l.status == "passed"),
                "failed": sum(1 for l in current_cycle_logs if l.status == "failed"),
                "error": sum(1 for l in current_cycle_logs if l.status == "error"),
                "skipped": sum(1 for l in current_cycle_logs if l.status == "skipped"),
                "cumulative_total_all_cycles": len(final.logs),
            },
        }
    )

    target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return target


def _print_summary(final: ProjectState, mode: str) -> None:
    print("\n" + "=" * 60)
    print(f"SENTINEL-QA  —  {mode.upper()} PIPELINE RESULTS")
    print("=" * 60)
    print(f"\nSTORY: {final.story_title} ({final.story_id})")
    print(f"Mode:  {final.pipeline_mode}")
    # v3 P0 — attestation headline. run_validity first; banner if not OK.
    _rv = final.metadata.get("run_validity", "OK")
    _cq = final.metadata.get("coverage_quality") or final.metadata.get("suite_quality")
    print(f"RUN VALIDITY: {_rv}   |   COVERAGE QUALITY: {_cq}")
    if _rv != "OK":
        ev = final.metadata.get("run_validity_evidence") or {}
        print(f"  ⚠ posture SUPPRESSED — {ev.get('reason', 'run did not validly exercise the app')}")
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
    summary = final.metadata.get("test_suite_summary")
    if summary and summary.get("by_category"):
        print("  By category (planned / executed / passed / failed / skipped / error):")
        order = summary.get("category_order") or list(summary["by_category"].keys())
        for cat in order:
            bucket = summary["by_category"].get(cat)
            if not bucket:
                continue
            line = (
                f"    {cat:18s}  planned={bucket['planned']:3d}  "
                f"executed={bucket.get('executed', 0):3d}  "
                f"passed={bucket.get('passed', 0):3d}  "
                f"failed={bucket.get('failed', 0):3d}  "
                f"skipped={bucket.get('skipped', 0):3d}  "
                f"error={bucket.get('error', 0):3d}"
            )
            if cat == "security" and (
                bucket.get("resilient") or bucket.get("vulnerable")
            ):
                line += (
                    f"  resilient={bucket.get('resilient', 0):3d}  "
                    f"vulnerable={bucket.get('vulnerable', 0):3d}"
                )
            print(line)
        # P1 — ISTQB / ISO 29119-4 technique breakdown.
        if summary.get("by_technique"):
            print("  By design technique (ISTQB / ISO 29119-4):")
            t_order = summary.get("technique_order") or list(summary["by_technique"].keys())
            for tech in t_order:
                tb = summary["by_technique"].get(tech)
                if not tb:
                    continue
                print(f"    {tech:22s}  planned={tb['planned']:3d}  executed={tb.get('executed', 0):3d}")
            eqp = summary.get("equivalence_partitions") or {}
            if eqp:
                covered = sorted({c for classes in eqp.values() for c in classes})
                print(f"    equivalence classes covered: {', '.join(covered)}")
    print(f"COVERAGE GAPS: {len(final.coverage_gaps)}")
    print(f"SUGGESTED PATCHES: {len(final.suggested_patches)}   <-- headline metric")
    posture = final.metadata.get("security_posture")
    if posture:
        print(f"SECURITY POSTURE (dynamic): {posture}")

    # SAST sidecar — static findings, clearly separated from dynamic posture.
    sast = final.metadata.get("sast_summary")
    if sast:
        if sast.get("ran"):
            bysev = sast.get("by_severity") or {}
            sev_str = ", ".join(f"{k}={v}" for k, v in bysev.items()) or "none"
            print(
                f"SAST (static, Bandit): {sast.get('findings_total', 0)} findings "
                f"across {sast.get('files_scanned', 0)} files  [{sev_str}]"
            )
            for f in (sast.get("top_findings") or [])[:3]:
                print(f"    - [{f.get('severity')}] {f.get('test_id')} {f.get('path')}:{f.get('line')} — {f.get('issue')}")
        else:
            print(f"SAST (static): not run — {sast.get('reason')}")

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
