"""Compare Phase 1 predictions against Phase 2 findings.

Drift report answers three questions:
  1. Which risks did Phase 1 predict that Phase 2 actually confirmed?
  2. Which predicted risks were NOT found in Phase 2 (checklist may have worked)?
  3. Which security checklist items appear to have been ignored by the developer?
"""

from __future__ import annotations

from typing import Any, Dict, List


def generate_drift_report(
    phase1_data: Dict[str, Any],
    phase2_state,
) -> Dict[str, Any]:
    """
    Args:
        phase1_data: Output of load_phase1() — the saved Phase 1 JSON.
        phase2_state: The ProjectState after Phase 2 completes.

    Returns:
        A dict written into state.metadata["drift_report"].
    """
    if not phase1_data:
        return {"error": "No Phase 1 data available for drift comparison."}

    # --- Risk drift ---
    predicted_risk_ids: List[str] = phase1_data.get("phase1_risk_ids", [])
    phase2_risk_ids: List[str] = [r.owasp_id for r in phase2_state.security_risks]

    confirmed_risks = [r for r in predicted_risk_ids if r in phase2_risk_ids]
    missed_risks = [r for r in predicted_risk_ids if r not in phase2_risk_ids]
    new_risks = [r for r in phase2_risk_ids if r not in predicted_risk_ids]

    # --- Vulnerability drift ---
    # Risks that were predicted AND an adversarial test actually found vulnerable
    exploited_owasp_ids = {
        log.exploit_target.split()[0] if log.exploit_target else ""
        for log in phase2_state.logs
        if log.is_vulnerable
    }
    confirmed_and_exploited = [r for r in confirmed_risks if r in exploited_owasp_ids]

    # --- Checklist drift ---
    # Check if any adversarial test failures map back to a checklist item
    checklist = phase1_data.get("security_checklist", [])
    ignored_checklist_items = []
    for item in checklist:
        owasp_id = item.get("owasp_id", "")
        was_exploited = any(
            log.is_vulnerable and (log.exploit_target or "").startswith(owasp_id.split(":")[0])
            for log in phase2_state.logs
        )
        if was_exploited:
            ignored_checklist_items.append({
                "owasp_id": owasp_id,
                "instruction": item.get("instruction"),
                "definition_of_done": item.get("definition_of_done"),
                "verdict": "IGNORED — vulnerability confirmed in Phase 2",
            })

    return {
        "story_id": phase1_data.get("story_id"),
        "summary": {
            "predicted": len(predicted_risk_ids),
            "confirmed_in_phase2": len(confirmed_risks),
            "missed_in_phase2": len(missed_risks),
            "new_in_phase2_only": len(new_risks),
            "exploited": len(confirmed_and_exploited),
            "checklist_items_ignored": len(ignored_checklist_items),
        },
        "confirmed_risks": confirmed_risks,
        "missed_risks": missed_risks,
        "new_risks_phase2_only": new_risks,
        "confirmed_and_exploited": confirmed_and_exploited,
        "ignored_checklist_items": ignored_checklist_items,
    }