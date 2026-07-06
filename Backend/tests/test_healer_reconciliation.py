"""Healer ↔ verdict reconciliation — the two judges must not contradict.

Encodes the r_0531fce0 / r_8e1084bd architectural gap: the verdict cascade
said "vulnerable" while the Healer — with the full error log and source
context — flagged the same failure as a test defect. Both shipped in one
artifact, so posture counted a vulnerability the Healer had already
debunked (single-identity IDOR workflow, status-list misexpectations).

Invariants pinned here:

  • A this-cycle Healer test-defect opt-out (empty target_file) downgrades
    the matching adversarial "vulnerable" verdict → "inconclusive", with
    the Healer's reasoning appended to the evidence chain and the
    reconciliation recorded in metadata.
  • Downgraded logs land in posture's unclassified bucket — never in
    vulnerable, never silently in resilient.
  • An actionable app patch (target_file set) does NOT downgrade anything.
  • Verdicts carrying hard body evidence ("body-evidence" marker) are
    never downgraded — response-body proof outranks the Healer's opinion.
  • Functional logs and non-vulnerable verdicts are untouched.
"""

from __future__ import annotations

from agents.executor import _reconcile_healer_verdicts, _security_posture
from state import ExecutionLog, Patch, ProjectState


def _state() -> ProjectState:
    return ProjectState(user_story="story", pipeline_mode="POST_CODE")


def _vuln_log(test_id: str = "TC-001", evidence: list[str] | None = None) -> ExecutionLog:
    return ExecutionLog(
        test_id=test_id,
        status="failed",
        is_adversarial=True,
        is_vulnerable=True,
        resilient=False,
        verdict="vulnerable",
        verdict_confidence="high",
        verdict_evidence=evidence
        or ["attestation_mode=defense_confirming — pytest fail means the defense did NOT hold"],
    )


def _defect_patch(test_id: str = "TC-001") -> Patch:
    return Patch(
        target_file="",
        bug_explanation="The test never set up a second identity; fetching your own task returns 200 — test defect.",
        suggested_fix="",
        related_test_ids=[test_id],
    )


def _app_patch(test_id: str = "TC-001") -> Patch:
    return Patch(
        target_file="routers/task_router.py",
        bug_explanation="task_id typed as str; FastAPI never validates UUID.",
        suggested_fix="task_id: UUID",
        related_test_ids=[test_id],
    )


def test_defect_optout_downgrades_vulnerable_to_inconclusive():
    state = _state()
    log = _vuln_log()
    _reconcile_healer_verdicts([log], [_defect_patch()], state)

    assert log.verdict == "inconclusive"
    assert log.is_vulnerable is None
    assert log.resilient is None
    assert log.verdict_confidence == "low"
    assert any("Healer reconciliation" in e for e in log.verdict_evidence)
    recs = state.metadata["healer_verdict_reconciliations"]
    assert recs[0]["test_id"] == "TC-001"
    assert recs[0]["previous_verdict"] == "vulnerable"


def test_downgraded_log_lands_in_unclassified_posture_bucket():
    state = _state()
    log = _vuln_log()
    _reconcile_healer_verdicts([log], [_defect_patch()], state)
    posture = _security_posture([log])

    assert posture["vulnerable"] == 0
    assert posture["unclassified"] == 1
    # Excluded from the resilience denominator entirely.
    assert posture["resilience_pct"] is None


def test_app_patch_does_not_downgrade():
    state = _state()
    log = _vuln_log()
    _reconcile_healer_verdicts([log], [_app_patch()], state)

    assert log.verdict == "vulnerable"
    assert log.is_vulnerable is True
    assert "healer_verdict_reconciliations" not in state.metadata


def test_body_evidence_outranks_healer_opinion():
    state = _state()
    log = _vuln_log(
        evidence=[
            "attestation_mode=defense_confirming — pytest fail means the defense did NOT hold",
            "body-evidence: forbidden token / exploit-success status hit",
        ],
    )
    _reconcile_healer_verdicts([log], [_defect_patch()], state)

    assert log.verdict == "vulnerable"
    assert log.is_vulnerable is True


def test_unrelated_test_id_untouched():
    state = _state()
    log = _vuln_log("TC-002")
    _reconcile_healer_verdicts([log], [_defect_patch("TC-001")], state)

    assert log.verdict == "vulnerable"


def test_functional_logs_untouched():
    state = _state()
    log = ExecutionLog(
        test_id="TC-001",
        status="failed",
        is_adversarial=False,
        passed=False,
        verdict="n/a",
    )
    _reconcile_healer_verdicts([log], [_defect_patch()], state)

    assert log.verdict == "n/a"
    assert log.passed is False
