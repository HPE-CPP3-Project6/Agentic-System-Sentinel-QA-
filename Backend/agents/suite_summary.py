"""Roll up test_suite + execution logs into categorized final-output buckets.

Consumed by executor_node (metadata) and main._dump_artifact (top-level JSON).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from state import ExecutionLog, SurfaceBinding, TestCase

# Display order for CLI / dashboard sections.
CATEGORY_ORDER: tuple[str, ...] = (
    "positive",
    "negative",
    "boundary",
    "state_transition",
    "security",
    "uncategorized",
)

_VALID_CATEGORIES = frozenset(CATEGORY_ORDER)


def _empty_category_bucket() -> Dict[str, int]:
    return {
        "planned": 0,
        "executed": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "error": 0,
        "resilient": 0,
        "vulnerable": 0,
        "inconclusive": 0,
        "off_target": 0,
    }


def _empty_owasp_bucket() -> Dict[str, int]:
    return {
        "planned": 0,
        "executed": 0,
        "resilient": 0,
        "vulnerable": 0,
        "skipped": 0,
        "errored": 0,
    }


def normalize_test_category(tc: TestCase) -> str:
    """Resolve display category for rollup (stable across Generator + Compiler)."""
    cat = (tc.test_category or "").strip().lower()
    if cat in _VALID_CATEGORIES:
        return cat
    if tc.is_adversarial:
        return "security"
    if len(tc.workflow_steps or []) >= 2:
        return "state_transition"
    if (tc.boundary_value_used or "").strip():
        return "boundary"
    esc = tc.expected_status_code
    if esc is not None and int(esc) >= 400:
        return "negative"
    return "uncategorized"


def _defense_kind_for_test(
    tc: TestCase,
    surface_map: Optional[Dict[str, SurfaceBinding]],
) -> Optional[str]:
    if not surface_map or not tc.covered_requirement_id:
        return None
    binding = surface_map.get(tc.covered_requirement_id)
    if binding is None:
        return None
    return binding.defense_kind


def _apply_log_to_category_bucket(bucket: Dict[str, int], tc: TestCase, log: ExecutionLog) -> None:
    bucket["executed"] += 1
    status = (log.status or "").lower()
    if status == "passed":
        bucket["passed"] += 1
    elif status == "failed":
        bucket["failed"] += 1
    elif status == "skipped":
        bucket["skipped"] += 1
    elif status == "error":
        bucket["error"] += 1

    verdict = log.verdict or "n/a"
    if verdict == "off_target":
        bucket["off_target"] += 1
    elif verdict == "inconclusive":
        bucket["inconclusive"] += 1
    elif tc.is_adversarial or (tc.test_category or "").lower() == "security":
        if log.resilient is True:
            bucket["resilient"] += 1
        elif log.is_vulnerable is True:
            bucket["vulnerable"] += 1


def _slim_test_entry(tc: TestCase, log: Optional[ExecutionLog], category: str) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "test_id": tc.test_id,
        "title": (tc.title or "")[:160],
        "test_category": category,
        "is_adversarial": tc.is_adversarial,
        "covered_requirement_id": tc.covered_requirement_id,
    }
    if tc.owasp_category:
        entry["owasp_category"] = tc.owasp_category
    if log is not None:
        entry["status"] = log.status
        entry["verdict"] = log.verdict
        if tc.is_adversarial:
            if log.resilient is True:
                entry["security_outcome"] = "resilient"
            elif log.is_vulnerable is True:
                entry["security_outcome"] = "vulnerable"
            elif log.status == "skipped":
                entry["security_outcome"] = "skipped"
            elif log.status == "error":
                entry["security_outcome"] = "error"
    return entry


def build_test_suite_summary(
    test_suite: List[TestCase],
    run_logs: List[ExecutionLog],
    *,
    surface_map: Optional[Dict[str, SurfaceBinding]] = None,
) -> Dict[str, Any]:
    """Build categorized counts + drill-down lists for artifact and CLI."""
    logs_by_id = {log.test_id: log for log in run_logs}

    by_category: Dict[str, Dict[str, int]] = {
        cat: _empty_category_bucket() for cat in CATEGORY_ORDER
    }
    tests_by_category: Dict[str, List[Dict[str, Any]]] = {
        cat: [] for cat in CATEGORY_ORDER
    }
    by_owasp: Dict[str, Dict[str, int]] = {}
    by_defense_kind: Dict[str, Dict[str, int]] = {}

    for tc in test_suite:
        category = normalize_test_category(tc)
        if category not in by_category:
            by_category[category] = _empty_category_bucket()
            tests_by_category[category] = []

        bucket = by_category[category]
        bucket["planned"] += 1

        log = logs_by_id.get(tc.test_id)
        if log is not None:
            _apply_log_to_category_bucket(bucket, tc, log)

        tests_by_category.setdefault(category, []).append(
            _slim_test_entry(tc, log, category)
        )

        if tc.is_adversarial and tc.owasp_category:
            owasp_key = tc.owasp_category
            ob = by_owasp.setdefault(owasp_key, _empty_owasp_bucket())
            ob["planned"] += 1
            if log is not None:
                ob["executed"] += 1
                if log.resilient is True:
                    ob["resilient"] += 1
                elif log.is_vulnerable is True:
                    ob["vulnerable"] += 1
                elif log.status == "error":
                    ob["errored"] += 1
                else:
                    ob["skipped"] += 1

        dk = _defense_kind_for_test(tc, surface_map)
        if dk:
            db = by_defense_kind.setdefault(
                dk,
                {"planned": 0, "executed": 0, "resilient": 0, "vulnerable": 0},
            )
            db["planned"] += 1
            if log is not None and (tc.is_adversarial or category == "security"):
                db["executed"] += 1
                if log.resilient is True:
                    db["resilient"] += 1
                elif log.is_vulnerable is True:
                    db["vulnerable"] += 1

    # Drop empty category keys from drill-down (keep buckets with planned > 0).
    tests_by_category = {
        k: v for k, v in tests_by_category.items() if v
    }

    totals = {
        "planned": len(test_suite),
        "executed": sum(1 for tc in test_suite if tc.test_id in logs_by_id),
    }

    return {
        "totals": totals,
        "by_category": {k: v for k, v in by_category.items() if v["planned"] > 0},
        "by_owasp": by_owasp,
        "by_defense_kind": by_defense_kind,
        "tests_by_category": tests_by_category,
        "category_order": list(CATEGORY_ORDER),
    }
