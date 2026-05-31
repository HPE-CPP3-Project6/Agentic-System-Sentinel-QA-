"""SAST sidecar — wrap Bandit for static analysis of the target source.

Phase 3A (v3 plan). This is the STATIC half of "shift-left: static + dynamic":
the pipeline already does dynamic API testing against a live app; Bandit reads
the SOURCE for known-bad patterns (SQLi sinks, `eval`, weak crypto, hardcoded
secrets, `subprocess(shell=True)`, …).

Design rules (kept deliberately):
  - SEPARATE metadata bucket: `sast_summary`. Never merged into the dynamic
    `security_posture` / `resilience_pct`.
  - NO Healer. SAST findings are reported, never auto-patched.
  - Graceful when Bandit isn't installed — emit `ran: False` with a reason,
    so a run on a machine without Bandit degrades honestly instead of crashing.

Usage:
    from tools.sast_scan import run_sast_scan
    summary = run_sast_scan(Path("repo_cache"))

CLI:
    python -m tools.sast_scan repo_cache
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

# Bandit severity/confidence are HIGH/MEDIUM/LOW; keep a stable display order.
_SEVERITY_ORDER = ("HIGH", "MEDIUM", "LOW", "UNDEFINED")


def _bandit_available(python: str) -> bool:
    try:
        r = subprocess.run(
            [python, "-m", "bandit", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_sast_scan(
    target_root: Path,
    *,
    python: Optional[str] = None,
    timeout_sec: int = 180,
    top_n: int = 5,
) -> Dict[str, Any]:
    """Run Bandit over `target_root` and return a compact summary dict.

    The summary is safe to embed in the artifact: counts + the top-N findings,
    not the full Bandit report.
    """
    python = python or sys.executable
    target_root = Path(target_root)

    if not target_root.is_dir():
        return {"tool": "bandit", "ran": False, "reason": f"target not found: {target_root}"}

    if not _bandit_available(python):
        return {
            "tool": "bandit",
            "ran": False,
            "reason": "bandit not installed — `pip install bandit` to enable static analysis",
        }

    # -r recurse, -f json machine-readable, -q quiet, skip vendored/test dirs.
    cmd = [
        python, "-m", "bandit", "-r", str(target_root),
        "-f", "json", "-q",
        "-x", "*/venv/*,*/.venv/*,*/node_modules/*,*/tests/*,*/__pycache__/*",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return {"tool": "bandit", "ran": False, "reason": f"bandit timed out after {timeout_sec}s"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"tool": "bandit", "ran": False, "reason": f"bandit invocation failed: {exc}"}

    # Bandit exits non-zero (1) when findings exist — that's NOT an error.
    # A real failure has empty stdout / unparseable JSON.
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {
            "tool": "bandit",
            "ran": False,
            "reason": "bandit produced unparseable output",
            "stderr_excerpt": (proc.stderr or "")[:400],
        }

    results: List[Dict[str, Any]] = report.get("results") or []
    metrics = report.get("metrics") or {}
    files_scanned = sum(
        1 for k in metrics.keys() if k not in ("_totals",)
    )

    by_severity = Counter(r.get("issue_severity", "UNDEFINED").upper() for r in results)
    by_confidence = Counter(r.get("issue_confidence", "UNDEFINED").upper() for r in results)
    by_test = Counter(
        f"{r.get('test_id', '?')}:{r.get('test_name', '?')}" for r in results
    )

    # Rank top findings: HIGH first, then MEDIUM, then LOW; high confidence first.
    sev_rank = {s: i for i, s in enumerate(_SEVERITY_ORDER)}
    ranked = sorted(
        results,
        key=lambda r: (
            sev_rank.get(r.get("issue_severity", "UNDEFINED").upper(), 99),
            -{"HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(r.get("issue_confidence", "LOW").upper(), 0),
        ),
    )
    top_findings = [
        {
            "test_id": r.get("test_id"),
            "test_name": r.get("test_name"),
            "severity": r.get("issue_severity"),
            "confidence": r.get("issue_confidence"),
            "issue": (r.get("issue_text") or "")[:160],
            "path": r.get("filename"),
            "line": r.get("line_number"),
            "cwe": (r.get("issue_cwe") or {}).get("id"),
        }
        for r in ranked[:top_n]
    ]

    return {
        "tool": "bandit",
        "ran": True,
        "target": str(target_root),
        "files_scanned": files_scanned,
        "findings_total": len(results),
        "by_severity": {s: by_severity.get(s, 0) for s in _SEVERITY_ORDER if by_severity.get(s)},
        "by_confidence": dict(by_confidence),
        "by_rule": dict(by_test.most_common(10)),
        "top_findings": top_findings,
        "note": "STATIC analysis — separate from dynamic security_posture; never auto-healed",
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("repo_cache")
    print(json.dumps(run_sast_scan(root), indent=2))
