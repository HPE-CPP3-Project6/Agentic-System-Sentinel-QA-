"""Compare Phase 1 predictions against Phase 2 findings.

Drift report answers three questions:
  1. Which risks did Phase 1 predict that Phase 2 actually confirmed?
  2. Which predicted risks were NOT found in Phase 2 (checklist may have worked)?
  3. Which security checklist items appear to have been ignored by the developer?

Identifier normalisation:
  OWASP ids reach this module in three different shapes:
    "A03"                        compiler short form
    "A03:2021"                   Critic SecurityRisk.owasp_id
    "A03:2021-Injection (SQLi)"  Executor log.exploit_target
                                 (Security+Compiler builds this string)
  Every comparison normalises both sides to the short form ("A03") via
  `_short_id` so the three shapes can never miss each other again. The
  previous version split exploit_target on whitespace, yielding
  "A03:2021-Injection" which never matched the Critic's "A03:2021" — so
  `confirmed_and_exploited` was almost always empty.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


def _short_id(owasp_id: str) -> str:
    """Reduce any OWASP id shape to its short prefix, e.g. 'A03'.

    Splits on the FIRST colon so 'A03:2021', 'A03:2021-Injection (SQLi)',
    and 'A07:2021-Authentication Failures' all reduce to 'A03' / 'A07'.
    Empty / falsy input returns ''.
    """
    if not owasp_id:
        return ""
    return owasp_id.split(":", 1)[0].strip().upper()


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

    # --- Risk drift (compare on normalised short ids) ---
    predicted_full: List[str] = phase1_data.get("phase1_risk_ids", []) or []
    phase2_full: List[str] = [r.owasp_id for r in phase2_state.security_risks]

    predicted_short: Set[str] = {_short_id(r) for r in predicted_full if r}
    phase2_short: Set[str] = {_short_id(r) for r in phase2_full if r}

    confirmed_short = predicted_short & phase2_short
    missed_short = predicted_short - phase2_short
    new_short = phase2_short - predicted_short

    # --- Vulnerability drift ---
    # Risks predicted in Phase 1 AND an adversarial test in Phase 2 found
    # vulnerable. Both sides normalised so 'A03:2021' (Critic) matches
    # 'A03:2021-Injection (SQLi)' (Executor exploit_target).
    exploited_short: Set[str] = {
        _short_id(log.exploit_target)
        for log in phase2_state.logs
        if log.is_vulnerable and log.exploit_target
    }
    confirmed_and_exploited_short = confirmed_short & exploited_short

    # --- Checklist drift ---
    # A predicted checklist item is "ignored" if the corresponding OWASP
    # category was successfully exploited in Phase 2 — meaning the developer
    # didn't satisfy the definition_of_done before pushing.
    checklist = phase1_data.get("security_checklist", []) or []
    ignored_checklist_items: List[Dict[str, Any]] = []
    confirmed_checklist_items: List[Dict[str, Any]] = []
    for item in checklist:
        owasp_short = _short_id(item.get("owasp_id", ""))
        if not owasp_short:
            continue
        if owasp_short in exploited_short:
            ignored_checklist_items.append({
                "owasp_id": item.get("owasp_id"),
                "requirement_id": item.get("requirement_id"),
                "instruction": item.get("instruction"),
                "definition_of_done": item.get("definition_of_done"),
                "verdict": "IGNORED — vulnerability confirmed in Phase 2",
            })
        elif owasp_short in confirmed_short:
            confirmed_checklist_items.append({
                "owasp_id": item.get("owasp_id"),
                "requirement_id": item.get("requirement_id"),
                "instruction": item.get("instruction"),
                "definition_of_done": item.get("definition_of_done"),
                "verdict": "ADDRESSED — risk confirmed and not exploited in Phase 2",
            })

    summary = {
        "predicted": len(predicted_short),
        "confirmed_in_phase2": len(confirmed_short),
        "missed_in_phase2": len(missed_short),
        "new_in_phase2_only": len(new_short),
        "exploited": len(confirmed_and_exploited_short),
        "checklist_items_ignored": len(ignored_checklist_items),
        "checklist_total": len(checklist),
        "checklist_addressed": len(confirmed_checklist_items),
    }

    return {
        "story_id": phase1_data.get("story_id"),
        "summary": summary,
        "headline": _build_headline(summary),
        "predicted_risks_full": predicted_full,
        "phase2_risks_full": phase2_full,
        "confirmed_risks": sorted(confirmed_short),
        "missed_risks": sorted(missed_short),
        "new_risks_phase2_only": sorted(new_short),
        "confirmed_and_exploited": sorted(confirmed_and_exploited_short),
        "confirmed_checklist_items": confirmed_checklist_items,
        "ignored_checklist_items": ignored_checklist_items,
    }


def _build_headline(summary: Dict[str, int]) -> Dict[str, str]:
    """Human-readable one-liner for UI / CLI."""
    predicted = summary.get("predicted", 0)
    confirmed = summary.get("confirmed_in_phase2", 0)
    missed = summary.get("missed_in_phase2", 0)
    new_only = summary.get("new_in_phase2_only", 0)
    exploited = summary.get("exploited", 0)
    ignored = summary.get("checklist_items_ignored", 0)

    if exploited > 0 or ignored > 0:
        parts = []
        if exploited:
            parts.append(f"{exploited} predicted risk(s) were exploited in POST_CODE")
        if ignored:
            parts.append(f"{ignored} shift-left checklist item(s) appear ignored")
        return {
            "status": "exploited",
            "message": "; ".join(parts) + ".",
        }

    if predicted == 0:
        return {
            "status": "no_prediction",
            "message": "PRE_CODE did not predict any OWASP risks for this story.",
        }

    if missed > 0:
        return {
            "status": "partial",
            "message": (
                f"{confirmed} of {predicted} predicted risk(s) confirmed in POST_CODE; "
                f"{missed} predicted risk(s) not surfaced in execution."
            ),
        }

    if new_only > 0:
        return {
            "status": "partial",
            "message": (
                f"All {predicted} predicted risk(s) confirmed; "
                f"{new_only} additional risk(s) found only in POST_CODE."
            ),
        }

    return {
        "status": "aligned",
        "message": (
            f"All {predicted} PRE_CODE risk prediction(s) confirmed in POST_CODE "
            "with no exploited vulnerabilities."
        ),
    }
