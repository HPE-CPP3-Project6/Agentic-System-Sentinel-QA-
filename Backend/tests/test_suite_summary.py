"""Tests for categorized test-suite rollup (final artifact sections)."""

from __future__ import annotations

from agents.suite_summary import build_test_suite_summary, normalize_test_category
from state import ExecutionLog, SurfaceBinding, TestCase


def test_normalize_test_category_adversarial_defaults_security():
    tc = TestCase(
        test_id="SEC-1",
        title="sqli",
        action="POST /login",
        expected_result="blocked",
        is_adversarial=True,
    )
    assert normalize_test_category(tc) == "security"


def test_build_test_suite_summary_groups_by_category():
    suite = [
        TestCase(
            test_id="TC-POS",
            title="happy",
            action="POST /tasks",
            expected_result="201",
            test_category="positive",
            expected_status_code=201,
        ),
        TestCase(
            test_id="TC-BND",
            title="max title",
            action="POST /tasks",
            expected_result="422",
            test_category="boundary",
            boundary_value_used="256 chars",
            expected_status_code=422,
        ),
        TestCase(
            test_id="SEC-A03-1",
            title="sqli",
            action="POST /login",
            expected_result="blocked",
            test_category="security",
            is_adversarial=True,
            owasp_category="A03:2021-Injection",
            exploit_target="A03:2021-Injection",
        ),
    ]
    logs = [
        ExecutionLog(
            test_id="TC-POS",
            status="passed",
            is_adversarial=False,
            passed=True,
            verdict="n/a",
        ),
        ExecutionLog(
            test_id="TC-BND",
            status="failed",
            is_adversarial=False,
            passed=False,
            verdict="n/a",
        ),
        ExecutionLog(
            test_id="SEC-A03-1",
            status="passed",
            is_adversarial=True,
            resilient=True,
            is_vulnerable=False,
            verdict="resilient",
            exploit_target="A03:2021-Injection",
        ),
    ]
    surface_map = {
        "REQ-001": SurfaceBinding(
            requirement_id="REQ-001",
            state="BACKEND_API",
            rationale="POST /login bound",
            confidence="high",
            threat_class="DEFENSIVE_INVERTED",
            defense_kind="INPUT_REJECTION",
        ),
    }
    suite[2].covered_requirement_id = "REQ-001"

    summary = build_test_suite_summary(suite, logs, surface_map=surface_map)

    assert summary["totals"]["planned"] == 3
    assert summary["totals"]["executed"] == 3
    assert summary["by_category"]["positive"]["planned"] == 1
    assert summary["by_category"]["positive"]["passed"] == 1
    assert summary["by_category"]["boundary"]["failed"] == 1
    assert summary["by_category"]["security"]["resilient"] == 1
    assert summary["by_owasp"]["A03:2021-Injection"]["resilient"] == 1
    assert summary["by_defense_kind"]["INPUT_REJECTION"]["planned"] == 1
    assert "positive" in summary["tests_by_category"]
    assert summary["tests_by_category"]["security"][0]["security_outcome"] == "resilient"
