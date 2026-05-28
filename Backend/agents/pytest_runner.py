"""Run Security+Compiler pytest output and map JUnit XML → ExecutionLog rows.

Wires generated `test_sentinel_api_generated.py` into the Executor when
`security_compiler_generated_files` is present. Disable with
`SENTINEL_EXECUTOR_RUN_PYTEST=0` to use the injected per-TestCase runner only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

from state import ExecutionLog, TestCase

from .security_compiler import slug_from_test_id

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _parse_junit_cases(junit_path: Path) -> Dict[str, Tuple[str, str]]:
    """Map pytest function name (`test_tc_req_001_01`) → (status, detail).

    status is passed | failed | error | skipped.
    """

    out: Dict[str, Tuple[str, str]] = {}
    if not junit_path.is_file():
        return out
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError:
        return out
    root = tree.getroot()
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        failure = case.find("failure")
        err_el = case.find("error")
        skipped = case.find("skipped")
        if failure is not None:
            msg = failure.get("message", "") or ""
            text = (failure.text or "")[:4000]
            out[name] = ("failed", f"{msg}\n{text}".strip())
        elif err_el is not None:
            msg = err_el.get("message", "") or ""
            text = (err_el.text or "")[:4000]
            out[name] = ("error", f"{msg}\n{text}".strip())
        elif skipped is not None:
            detail = skipped.get("message", "") or (skipped.text or "") or "skipped"
            out[name] = ("skipped", str(detail)[:2000])
        else:
            out[name] = ("passed", "")
    return out


def run_pytest_generated_file(
    test_suite: List[TestCase],
    py_path: Path,
    *,
    cwd: Path | None = None,
    timeout_sec: int | None = None,
) -> Tuple[List[ExecutionLog], int, str, str]:
    """Run ``pytest <file>`` with JUnit XML, return logs aligned to ``test_suite`` order."""

    work_cwd = cwd or BACKEND_ROOT
    if timeout_sec is None:
        timeout_sec = int(os.getenv("SENTINEL_PYTEST_TIMEOUT_SEC", "900"))

    tmp_dir = Path(tempfile.mkdtemp(prefix="sentinel_junit_"))
    junit_path = tmp_dir / "junit.xml"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(py_path.resolve()),
        "-q",
        "--tb=short",
        f"--junitxml={junit_path}",
        "-o",
        "junit_family=xunit2",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(work_cwd.resolve()),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired as exc:
        # A hung target API or pathological test would otherwise propagate
        # TimeoutExpired out of executor_node and crash the LangGraph run.
        # Convert into one error-status ExecutionLog per test so needs_healing
        # sees the failure and routes "heal" once (bounded by max_heal_attempts)
        # instead of the whole graph aborting.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        stdout_part = (exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
        stderr_part = (exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
        timeout_msg = (
            f"pytest subprocess exceeded {timeout_sec}s timeout — target API hung "
            f"or test is pathological. Killed and converted to per-test error logs."
        )
        timeout_logs: List[ExecutionLog] = [
            ExecutionLog(
                test_id=tc.test_id,
                status="error",
                is_adversarial=tc.is_adversarial,
                passed=False if not tc.is_adversarial else None,
                is_vulnerable=None,
                resilient=None,
                exploit_target=tc.exploit_target,
                stderr=timeout_msg,
            )
            for tc in test_suite
        ]
        return timeout_logs, -1, stdout_part, (stderr_part + "\n" + timeout_msg).strip()

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    cases = _parse_junit_cases(junit_path)

    logs: List[ExecutionLog] = []
    for tc in test_suite:
        # NEW-2: propagate exploit_target onto every log so security_posture's
        # by_exploit_target breakdown shows per-OWASP buckets instead of one
        # giant "unknown" bucket. Demo-artifact bug was exactly this.
        et = tc.exploit_target
        func_name = "test_" + slug_from_test_id(tc.test_id)
        if func_name not in cases:
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="error",
                    is_adversarial=tc.is_adversarial,
                    passed=False if not tc.is_adversarial else None,
                    is_vulnerable=None,
                    resilient=None,
                    exploit_target=et,
                    stderr=(
                        f"No JUnit entry for `{func_name}` "
                        f"(emit truncated, collect error, or slug drift). "
                        f"pytest exit={proc.returncode}"
                    ),
                )
            )
            continue

        st, detail = cases[func_name]
        if st == "passed":
            if tc.is_adversarial:
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="passed",
                        is_adversarial=True,
                        is_vulnerable=False,
                        resilient=True,
                        exploit_target=et,
                        stdout=detail[:2000] if detail else None,
                    )
                )
            else:
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="passed",
                        is_adversarial=False,
                        passed=True,
                        exploit_target=et,
                        stdout=detail[:2000] if detail else None,
                    )
                )
        elif st == "skipped":
            # A skipped test never observed the attacker class (or for functional
            # tests: never observed the behaviour under test). It MUST NOT be
            # rolled into resilient/passed counts — that would manufacture
            # phantom security posture from tests that did not run.
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="skipped",
                    is_adversarial=tc.is_adversarial,
                    passed=None,
                    is_vulnerable=None,
                    resilient=None,
                    exploit_target=et,
                    stderr=("pytest skipped: " + detail)[:4000],
                )
            )
        elif st == "failed":
            if tc.is_adversarial:
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="failed",
                        is_adversarial=True,
                        is_vulnerable=True,
                        resilient=False,
                        exploit_target=et,
                        stderr=detail[:8000],
                    )
                )
            else:
                logs.append(
                    ExecutionLog(
                        test_id=tc.test_id,
                        status="failed",
                        is_adversarial=False,
                        passed=False,
                        exploit_target=et,
                        stderr=detail[:8000],
                    )
                )
        else:  # error
            logs.append(
                ExecutionLog(
                    test_id=tc.test_id,
                    status="error",
                    is_adversarial=tc.is_adversarial,
                    passed=False if not tc.is_adversarial else None,
                    is_vulnerable=None,
                    resilient=None,
                    exploit_target=et,
                    stderr=detail[:8000],
                )
            )

    shutil.rmtree(tmp_dir, ignore_errors=True)

    return logs, proc.returncode, stdout, stderr
