"""FUNCTIONALLY_UNRELIABLE detector — two-gate rule.

Encodes the r_8e1084bd inversion: a 32-test run with 29 passing and 2
defective failures scored defect_ratio=1.0 (defects / FAILURES) and branded
the entire run unreliable — suppressing the resilience headline — even
though the suite demonstrably exercised the app. The better a suite passes,
the more a couple of bad tests dominated the old failure-denominator ratio.

The detector now requires BOTH:
  1. defect_ratio  >= 30% of functional failures (failures are mostly noise)
  2. suite share   >= 20% of executed functional tests (enough of the suite
     is broken to distrust the run as a whole)
"""

from __future__ import annotations

from agents.executor import _detect_functional_unreliability
from state import ExecutionLog, Patch


def _func_log(test_id: str, passed: bool) -> ExecutionLog:
    return ExecutionLog(
        test_id=test_id,
        status="passed" if passed else "failed",
        is_adversarial=False,
        passed=passed,
        verdict="n/a",
    )


def _optout_patch(*test_ids: str) -> Patch:
    return Patch(
        target_file="",
        bug_explanation="test defect — wrong expected status",
        suggested_fix="",
        related_test_ids=list(test_ids),
    )


def _app_patch(*test_ids: str) -> Patch:
    return Patch(
        target_file="routers/task_router.py",
        bug_explanation="real bug",
        suggested_fix="fix",
        related_test_ids=list(test_ids),
    )


def test_large_green_suite_with_two_defective_failures_is_not_unreliable():
    """The r_8e1084bd case: 29 passed + 2 defective failures must stay OK."""
    logs = [_func_log(f"TC-{i:03d}", passed=True) for i in range(29)]
    logs += [_func_log("TC-F1", passed=False), _func_log("TC-F2", passed=False)]
    patches = [_optout_patch("TC-F1"), _optout_patch("TC-F2")]

    assert _detect_functional_unreliability(logs, patches) is None


def test_small_suite_with_one_defective_failure_is_unreliable():
    """3 tests, 1 defective failure = a third of the suite is broken — flag."""
    logs = [
        _func_log("TC-001", passed=True),
        _func_log("TC-002", passed=True),
        _func_log("TC-003", passed=False),
    ]
    ev = _detect_functional_unreliability(logs, [_optout_patch("TC-003")])

    assert ev is not None
    assert ev["defect_suite_share"] >= 0.20
    assert ev["defect_ratio"] == 1.0


def test_mostly_real_bug_failures_are_not_unreliable():
    """Failures dominated by actionable app patches — ratio gate stays off."""
    logs = [_func_log(f"TC-{i}", passed=False) for i in range(4)]
    patches = [
        _app_patch("TC-0"),
        _app_patch("TC-1"),
        _app_patch("TC-2"),
        _optout_patch("TC-3"),  # 1/4 = 25% < 30% ratio gate
    ]

    assert _detect_functional_unreliability(logs, patches) is None


def test_broken_suite_fires_both_gates():
    """5 executed, 3 defective failures: ratio 1.0, share 0.6 — unreliable."""
    logs = [_func_log("TC-OK1", passed=True), _func_log("TC-OK2", passed=True)]
    logs += [_func_log(f"TC-F{i}", passed=False) for i in range(3)]
    patches = [_optout_patch("TC-F0", "TC-F1", "TC-F2")]

    ev = _detect_functional_unreliability(logs, patches)
    assert ev is not None
    assert ev["test_defect_failures"] == 3
    assert ev["functional_executed"] == 5


def test_no_failures_returns_none():
    logs = [_func_log("TC-001", passed=True)]
    assert _detect_functional_unreliability(logs, []) is None
