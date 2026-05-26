"""Golden tests for the four Executor bug fixes.

Each test pins exactly one of the regressions that motivated the recent
Executor rework — they exist so the next refactor cannot silently re-break
the heal loop, the security posture, or the timeout path.

Run from Backend/:
    pytest tests/test_executor.py -v
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agents import executor as exec_mod
from agents import pytest_runner
from agents.executor import RunnerResult, _security_posture, executor_node, needs_healing
from state import ExecutionLog, ProjectState, TestCase


# --------------------------------------------------------------------------- #
# B1 — needs_healing must only see the current heal attempt's logs            #
# --------------------------------------------------------------------------- #


def test_needs_healing_only_inspects_current_attempt():
    """A stale failed log from attempt 1 must NOT cause routing back to heal
    after attempt 2 has actually cleared the problem.
    """
    state = ProjectState(
        user_story="test story",
        heal_attempts=2,
        max_heal_attempts=10,  # well above current, so cap doesn't end us
    )
    state.logs = [
        # Stale failure from attempt 1 — must be ignored.
        ExecutionLog(
            test_id="TC-1",
            status="failed",
            is_adversarial=False,
            passed=False,
            heal_attempt=1,
        ),
        # Current attempt is clean.
        ExecutionLog(
            test_id="TC-1",
            status="passed",
            is_adversarial=False,
            passed=True,
            heal_attempt=2,
        ),
    ]
    assert needs_healing(state) == "end"


def test_needs_healing_routes_heal_when_current_attempt_fails():
    """Sanity: when the current attempt does have a failure, route to heal."""
    state = ProjectState(
        user_story="test story",
        heal_attempts=1,
        max_heal_attempts=2,
    )
    state.logs = [
        ExecutionLog(
            test_id="TC-1",
            status="failed",
            is_adversarial=False,
            passed=False,
            heal_attempt=1,
        ),
    ]
    assert needs_healing(state) == "heal"


# --------------------------------------------------------------------------- #
# B2 — executor_node must stamp every new log with heal_attempt               #
# --------------------------------------------------------------------------- #


def test_executor_stamps_logs_with_heal_attempt(monkeypatch):
    """Every ExecutionLog produced in this run must carry the current heal_attempts."""
    # All-pass runner: no _heal call, so the LLM stub is never actually invoked.
    monkeypatch.setattr(exec_mod, "get_local_llm", lambda **kw: None)

    state = ProjectState(
        user_story="test story",
        test_suite=[
            TestCase(test_id="TC-1", title="t1", action="GET /x", expected_result="ok"),
            TestCase(test_id="TC-2", title="t2", action="GET /y", expected_result="ok"),
        ],
    )

    def ok_runner(tc: TestCase) -> RunnerResult:
        return RunnerResult(ok=True)

    result = executor_node(state, runner=ok_runner)

    assert result.heal_attempts == 1
    assert len(result.logs) == 2
    assert all(l.heal_attempt == 1 for l in result.logs), (
        "every new log must carry heal_attempt == state.heal_attempts"
    )


# --------------------------------------------------------------------------- #
# B3 — skipped adversarial tests must NOT count as resilient                  #
# --------------------------------------------------------------------------- #


def test_skipped_adversarial_not_counted_as_resilient():
    """A skipped adversarial test never fired the attack. Counting it as
    resilient would manufacture phantom security posture.
    """
    logs = [
        # Skipped attack — never executed.
        ExecutionLog(
            test_id="SEC-A03-1",
            status="skipped",
            is_adversarial=True,
            is_vulnerable=None,
            resilient=None,
            exploit_target="A03:2021-Injection",
        ),
        # Real blocked attack — resilient.
        ExecutionLog(
            test_id="SEC-A03-2",
            status="passed",
            is_adversarial=True,
            is_vulnerable=False,
            resilient=True,
            exploit_target="A03:2021-Injection",
        ),
        # Successful exploit — vulnerable.
        ExecutionLog(
            test_id="SEC-A03-3",
            status="failed",
            is_adversarial=True,
            is_vulnerable=True,
            resilient=False,
            exploit_target="A03:2021-Injection",
        ),
    ]

    posture = _security_posture(logs)

    assert posture["attempted"] == 3
    assert posture["resilient"] == 1, "skipped must NOT inflate resilient count"
    assert posture["vulnerable"] == 1
    assert posture["skipped"] == 1
    assert posture["errored"] == 0
    # Internal consistency: every adversarial bucket is one of the four states.
    assert (
        posture["resilient"] + posture["vulnerable"]
        + posture["skipped"] + posture["errored"]
        == posture["attempted"]
    )
    # Resilience % is over DECIDED tests only — skipped/errored excluded from denominator.
    assert posture["resilience_pct"] == 50.0  # 1 resilient / 2 decided

    by_t = posture["by_exploit_target"]["A03:2021-Injection"]
    assert by_t == {
        "attempted": 3, "resilient": 1, "vulnerable": 1, "skipped": 1, "errored": 0,
    }


# --------------------------------------------------------------------------- #
# B3+C6 — error MUST NOT be conflated with skipped                            #
# --------------------------------------------------------------------------- #


def test_errored_adversarial_not_counted_as_skipped_or_resilient():
    """A pytest_runner timeout produces status='error' with verdicts both None.
    Previously this lumped into the 'skipped' bucket, lying about how much was
    deliberately filtered out vs how much fell over.
    """
    logs = [
        # Timeout-converted-to-error adversarial.
        ExecutionLog(
            test_id="SEC-A03-1",
            status="error",
            is_adversarial=True,
            is_vulnerable=None,
            resilient=None,
            exploit_target="A03:2021-Injection",
            stderr="pytest subprocess exceeded 900s timeout",
        ),
        # Explicit skip (no JWT, parametrize, etc.).
        ExecutionLog(
            test_id="SEC-A03-2",
            status="skipped",
            is_adversarial=True,
            is_vulnerable=None,
            resilient=None,
            exploit_target="A03:2021-Injection",
        ),
        # Decided resilient.
        ExecutionLog(
            test_id="SEC-A03-3",
            status="passed",
            is_adversarial=True,
            is_vulnerable=False,
            resilient=True,
            exploit_target="A03:2021-Injection",
        ),
    ]

    posture = _security_posture(logs)

    assert posture["attempted"] == 3
    assert posture["resilient"] == 1
    assert posture["vulnerable"] == 0
    assert posture["skipped"] == 1, "explicit skip stays in skipped"
    assert posture["errored"] == 1, "timeout-error must NOT count as skipped"
    assert posture["resilience_pct"] == 100.0  # 1 resilient / 1 decided

    by_t = posture["by_exploit_target"]["A03:2021-Injection"]
    assert by_t == {
        "attempted": 3, "resilient": 1, "vulnerable": 0, "skipped": 1, "errored": 1,
    }


# --------------------------------------------------------------------------- #
# B4 — pytest subprocess timeout must not crash the graph                     #
# --------------------------------------------------------------------------- #


def test_pytest_runner_handles_timeout(monkeypatch, tmp_path: Path):
    """A subprocess.TimeoutExpired must be caught and converted to error logs.

    Previously: TimeoutExpired propagated out of executor_node and crashed the
    whole LangGraph run. Now: rc=-1, one error log per test, graph survives.
    """
    fake_py = tmp_path / "fake_tests.py"
    fake_py.write_text("# placeholder pytest target\n")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0] if args else ["pytest"],
            timeout=kwargs.get("timeout", 1),
        )

    monkeypatch.setattr(pytest_runner.subprocess, "run", fake_run)

    suite = [
        TestCase(test_id="TC-1", title="t1", action="GET /x", expected_result="ok"),
        TestCase(test_id="TC-2", title="t2", action="POST /y", expected_result="ok",
                 is_adversarial=True),
    ]

    logs, rc, stdout, stderr = pytest_runner.run_pytest_generated_file(
        suite, fake_py, timeout_sec=1,
    )

    assert rc == -1, "timeout must signal rc=-1 to the executor"
    assert len(logs) == 2, "one error log emitted per TestCase on timeout"
    assert all(l.status == "error" for l in logs)
    assert "timeout" in stderr.lower()
    # Functional verdict for non-adversarial test should be passed=False;
    # adversarial verdicts (is_vulnerable / resilient) must stay None.
    func_log = next(l for l in logs if l.test_id == "TC-1")
    adv_log = next(l for l in logs if l.test_id == "TC-2")
    assert func_log.passed is False
    assert adv_log.is_vulnerable is None
    assert adv_log.resilient is None
