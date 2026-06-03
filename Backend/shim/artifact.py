from __future__ import annotations

from typing import Any

from state import ProjectState


def _serialize_input_data(tc: Any) -> dict[str, Any] | list[Any]:
    """Pass through generator payloads for the UI (dict or workflow step list)."""
    data = getattr(tc, "input_data", None)
    if data is None:
        return {}
    if isinstance(data, (dict, list)):
        return data
    return {"value": data}


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

    # Join logs with their TestCase so the UI findings table can show
    # category / technique / title + evidence per row (Fortify-style) without
    # a second lookup.
    _tc_by_id = {tc.test_id: tc for tc in state.test_suite}
    logs_detail = []
    for l in current_cycle_logs:
        tc = _tc_by_id.get(l.test_id)
        logs_detail.append(
            {
                "test_id": l.test_id,
                "status": l.status,
                "verdict": getattr(l, "verdict", "n/a"),
                "verdict_confidence": getattr(l, "verdict_confidence", "low"),
                "duration_ms": l.duration_ms,
                "exploit_target": l.exploit_target,
                "is_adversarial": l.is_adversarial,
                "category": getattr(tc, "test_category", None) if tc else None,
                "technique": getattr(tc, "test_technique", None) if tc else None,
                "title": (getattr(tc, "title", None) if tc else None) or l.test_id,
                "verdict_evidence": (getattr(l, "verdict_evidence", None) or [])[:4],
                "stderr_excerpt": (l.stderr or "")[:300] if l.status in ("failed", "error") else None,
                # Stage-1 attestation: surface the mode that drove the verdict
                # cascade so the findings row shows whether this test was
                # attesting a gap (missing_control) or verifying a defense
                # (defense_confirming). Null on functional tests.
                "attestation_mode": getattr(tc, "attestation_mode", None) if tc else None,
            }
        )

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
                "input_data": _serialize_input_data(tc),
                "source_refs": tc.source_refs,
                # Stage-3 — surfaces the actual header assertions so the
                # frontend findings table can show "verifies X-Frame-Options"
                # next to the test row, and so a reviewer eyeballing the
                # artifact JSON can confirm the test isn't a header-claim
                # false-green.
                "required_response_headers": getattr(tc, "required_response_headers", None) or {},
                "attestation_mode": getattr(tc, "attestation_mode", None),
            }
        )

    patch_decisions = state.metadata.get("patch_decisions") or {}
    suggested_patches = []
    for i, p in enumerate(state.suggested_patches):
        patch_id = f"patch-{i + 1}"
        fix_preview = (p.suggested_fix or "")[:120]
        explanation = (p.bug_explanation or "")[:200]
        suggested_patches.append(
            {
                "patch_id": patch_id,
                "test_id": (p.related_test_ids or ["unknown"])[0],
                "summary": explanation or fix_preview or "Healer suggestion",
                "decision": patch_decisions.get(patch_id, "pending"),
                "target_file": (p.target_file or "").strip(),
                "bug_explanation": p.bug_explanation or "",
                "suggested_fix": p.suggested_fix or "",
                "related_test_ids": list(p.related_test_ids or []),
                "owasp_category": p.owasp_category,
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
