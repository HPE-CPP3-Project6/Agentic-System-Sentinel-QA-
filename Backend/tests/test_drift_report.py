"""Golden tests for phase_bridge.drift_report (C2 fix).

Pins the behavior that the THREE OWASP id shapes —
    "A03"                          (compiler short form)
    "A03:2021"                     (Critic SecurityRisk.owasp_id)
    "A03:2021-Injection (SQLi)"    (Executor log.exploit_target)
— all reduce to the same short id ("A03") so `confirmed_and_exploited`
is no longer always-empty.

Run from Backend/:
    pytest tests/test_drift_report.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from phase_bridge.drift_report import _short_id, generate_drift_report
from state import ExecutionLog, SecurityRisk


# --------------------------------------------------------------------------- #
# _short_id — the normalization primitive everything else depends on          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("inp,expected", [
    ("A03", "A03"),
    ("A03:2021", "A03"),
    ("A03:2021-Injection", "A03"),
    ("A03:2021-Injection (SQLi)", "A03"),
    ("a03:2021", "A03"),
    ("  A07:2021-Authentication Failures  ", "A07"),
    ("", ""),
    (None, ""),
])
def test_short_id_normalises_every_observed_shape(inp, expected):
    assert _short_id(inp) == expected


# --------------------------------------------------------------------------- #
# Helpers — build phase1 + phase2 state for the cross-shape match scenario    #
# --------------------------------------------------------------------------- #


def _phase1(predicted_full_ids: List[str], checklist: list | None = None) -> dict:
    return {
        "story_id": "TEST-001",
        "phase1_risk_ids": predicted_full_ids,
        "security_checklist": checklist or [],
    }


def _phase2_state(
    *,
    risks: List[str] | None = None,
    exploited_targets: List[str] | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for ProjectState — drift_report only reads two fields."""
    security_risks = [
        SecurityRisk(owasp_id=r, title="x", severity="Medium", rationale="x")
        for r in (risks or [])
    ]
    logs = [
        ExecutionLog(
            test_id=f"SEC-{i}",
            status="failed",
            is_adversarial=True,
            is_vulnerable=True,
            resilient=False,
            exploit_target=target,
        )
        for i, target in enumerate(exploited_targets or [])
    ]
    return SimpleNamespace(security_risks=security_risks, logs=logs)


# --------------------------------------------------------------------------- #
# The bug C2 fixed: confirmed_and_exploited was always empty                  #
# --------------------------------------------------------------------------- #


def test_confirmed_and_exploited_matches_across_id_shapes():
    """The headline regression — Critic emits 'A03:2021', Executor's
    exploit_target is 'A03:2021-Injection (SQLi)'. Pre-fix these never
    matched and `confirmed_and_exploited` was empty. Post-fix both
    reduce to 'A03' and the match succeeds.
    """
    phase1 = _phase1(["A03:2021", "A04:2021"])
    state = _phase2_state(
        risks=["A03:2021", "A04:2021"],   # both predicted risks confirmed
        exploited_targets=["A03:2021-Injection (SQLi)"],  # one was exploited
    )

    drift = generate_drift_report(phase1, state)

    assert drift["confirmed_risks"] == ["A03", "A04"]
    assert drift["confirmed_and_exploited"] == ["A03"]
    assert drift["summary"]["exploited"] == 1
    assert drift["summary"]["confirmed_in_phase2"] == 2
    assert drift["headline"]["status"] == "exploited"
    assert drift["predicted_risks_full"] == ["A03:2021", "A04:2021"]


def test_predicted_risk_not_in_phase2_lands_in_missed():
    phase1 = _phase1(["A03:2021", "A01:2021"])
    state = _phase2_state(risks=["A03:2021"])  # only A03 confirmed

    drift = generate_drift_report(phase1, state)

    assert drift["confirmed_risks"] == ["A03"]
    assert drift["missed_risks"] == ["A01"]
    assert drift["new_risks_phase2_only"] == []


def test_phase2_only_risks_land_in_new_bucket():
    """A risk that Phase 1 did NOT predict but Phase 2 did find should show
    up in `new_risks_phase2_only` — useful for grading PRE_CODE accuracy.
    """
    phase1 = _phase1(["A03:2021"])
    state = _phase2_state(risks=["A03:2021", "A07:2021"])

    drift = generate_drift_report(phase1, state)

    assert drift["confirmed_risks"] == ["A03"]
    assert drift["missed_risks"] == []
    assert drift["new_risks_phase2_only"] == ["A07"]


def test_checklist_item_ignored_when_corresponding_owasp_exploited():
    """The money slide: a Phase-1 checklist item flagged as IGNORED iff its
    OWASP category was successfully exploited in Phase 2 — meaning the
    developer didn't satisfy the definition_of_done.
    """
    phase1 = _phase1(
        ["A03:2021"],
        checklist=[
            {
                "owasp_id": "A03:2021",
                "instruction": "Parameterise all SQL queries.",
                "definition_of_done": "Verified when no string interpolation in queries.",
            },
        ],
    )
    state = _phase2_state(
        risks=["A03:2021"],
        exploited_targets=["A03:2021-Injection (SQLi)"],
    )

    drift = generate_drift_report(phase1, state)

    assert drift["summary"]["checklist_items_ignored"] == 1
    item = drift["ignored_checklist_items"][0]
    assert item["owasp_id"] == "A03:2021"
    assert item["instruction"] == "Parameterise all SQL queries."
    assert "IGNORED" in item["verdict"]


def test_empty_phase1_returns_error_not_crash():
    drift = generate_drift_report({}, _phase2_state(risks=["A03:2021"]))
    assert "error" in drift
    assert "No Phase 1 data" in drift["error"]


def test_no_exploits_clears_confirmed_and_exploited():
    """All adversarial tests resilient → exploited set empty → no false IGNOREDs."""
    phase1 = _phase1(
        ["A03:2021"],
        checklist=[{"owasp_id": "A03:2021", "instruction": "x", "definition_of_done": "y"}],
    )
    # state has the predicted risk but NO is_vulnerable=True logs
    state = SimpleNamespace(
        security_risks=[
            SecurityRisk(owasp_id="A03:2021", title="x", severity="Medium", rationale="x")
        ],
        logs=[
            ExecutionLog(
                test_id="SEC-1",
                status="passed",
                is_adversarial=True,
                is_vulnerable=False,
                resilient=True,
                exploit_target="A03:2021-Injection (SQLi)",
            ),
        ],
    )

    drift = generate_drift_report(phase1, state)

    assert drift["confirmed_and_exploited"] == []
    assert drift["ignored_checklist_items"] == []
    assert drift["summary"]["exploited"] == 0
    assert drift["summary"]["checklist_items_ignored"] == 0
    assert drift["summary"]["checklist_addressed"] == 1
    assert len(drift["confirmed_checklist_items"]) == 1
    assert drift["headline"]["status"] == "aligned"
