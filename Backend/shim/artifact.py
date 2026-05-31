from __future__ import annotations

from typing import Any

from state import ProjectState


def state_to_artifact(state: ProjectState) -> dict[str, Any]:
    """Mirror main._dump_artifact envelope + frontend-friendly extras."""
    md = {k: v for k, v in state.metadata.items() if k not in ("critic_raw", "generator_raw")}
    final_attempt = state.heal_attempts
    current_cycle_logs = (
        [l for l in state.logs if l.heal_attempt == final_attempt]
        if final_attempt > 0
        else list(state.logs)
    )

    run_validity = state.metadata.get("run_validity", "OK")
    coverage_quality = state.metadata.get("coverage_quality") or state.metadata.get("suite_quality")
    attestation_banner = None
    if run_validity == "DESIGN_ONLY":
        attestation_banner = (
            "PRE_CODE design artifact — no execution. Read design_contracts and security_checklist."
        )
    elif run_validity != "OK":
        ev = state.metadata.get("run_validity_evidence") or {}
        attestation_banner = (
            f"run_validity={run_validity} — {ev.get('reason', 'run did not validly exercise the app')}"
        )

    logs_detail = [
        {
            "test_id": l.test_id,
            "status": l.status,
            "verdict": getattr(l, "verdict", "n/a"),
            "verdict_confidence": getattr(l, "verdict_confidence", "low"),
            "duration_ms": l.duration_ms,
            "exploit_target": l.exploit_target,
        }
        for l in current_cycle_logs
    ]

    posture = state.metadata.get("security_posture")

    test_suite = []
    for tc in state.test_suite:
        method, _, path = (tc.action or "GET /").partition(" ")
        test_suite.append(
            {
                "test_id": tc.test_id,
                "title": tc.title or tc.test_id,
                "category": tc.test_category,
                "technique": tc.test_technique,
                "equivalence_class": tc.equivalence_class,
                "method": tc.bound_method or method.strip() or "GET",
                "path": tc.bound_path or path.strip() or "/",
                "expected_status_code": tc.expected_status_code,
                "adversarial": tc.is_adversarial,
                "forbidden_response_content": tc.forbidden_response_content,
                "input_data": {},
                "source_refs": tc.source_refs,
            }
        )

    suggested_patches = []
    for i, p in enumerate(state.suggested_patches):
        suggested_patches.append(
            {
                "patch_id": f"patch-{i+1}",
                "test_id": (p.related_test_ids or ["unknown"])[0],
                "summary": p.bug_explanation or p.suggested_fix[:120],
                "decision": "pending",
            }
        )

    return {
        "story_id": state.story_id,
        "story_title": state.story_title,
        "pipeline_mode": state.pipeline_mode,
        "run_validity": run_validity,
        "coverage_quality": coverage_quality,
        "attestation_banner": attestation_banner,
        "suite_quality": state.metadata.get("suite_quality"),
        "test_suite_summary": state.metadata.get("test_suite_summary"),
        "design_summary": state.metadata.get("design_summary"),
        "surface_map": {
            req_id: {
                **binding.model_dump(),
                "req_id": req_id,
                "requirement_text": binding.rationale,
            }
            for req_id, binding in (state.surface_map or {}).items()
        },
        "test_suite": test_suite,
        "execution_logs": logs_detail,
        "security_posture": posture,
        "resilience_pct": (posture or {}).get("resilience_pct") if posture else None,
        "design_contracts": [c.model_dump() for c in state.design_contracts],
        "security_checklist": [i.model_dump() for i in state.security_checklist],
        "suggested_patches": suggested_patches,
        "drift_report": state.metadata.get("drift_report"),
        "sast_summary": state.metadata.get("sast_summary"),
        "logs_summary": {
            "total": len(current_cycle_logs),
            "passed": sum(1 for l in current_cycle_logs if l.status == "passed"),
            "failed": sum(1 for l in current_cycle_logs if l.status == "failed"),
        },
        "metadata": md,
    }
