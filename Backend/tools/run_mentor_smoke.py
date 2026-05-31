"""Run mentor catalog smoke stories and print a summary table."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

STORIES = [
    "req-fr-filter",
    "req-fr-user-mgmt",
    "req-fr-task-create",
    "req-fr-search",
    "req-nfr-security",
]

BACKEND = Path(__file__).resolve().parent.parent
OUTPUTS = BACKEND.parent / "outputs"
ARTIFACT_RE = re.compile(r"Artifact written:\s*(.+)", re.IGNORECASE)


def main() -> int:
    rows: list[dict] = []
    for key in STORIES:
        print(f"\n{'='*60}\nSMOKE: {key}\n{'='*60}", flush=True)
        proc = subprocess.run(
            [sys.executable, "main.py", "--mode", "post_code", key],
            cwd=str(BACKEND),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        print(stdout, end="")
        if stderr:
            print(stderr, file=sys.stderr, end="")
        artifact_path: Path | None = None
        for stream in (stdout, stderr):
            m = ARTIFACT_RE.search(stream)
            if m:
                artifact_path = Path(m.group(1).strip())
                break
        row = {
            "story": key,
            "exit": proc.returncode,
            "artifact": str(artifact_path) if artifact_path else None,
        }
        if artifact_path and artifact_path.is_file():
            data = json.loads(artifact_path.read_text(encoding="utf-8"))
            ls = data.get("logs_summary") or {}
            row.update(
                {
                    "run_validity": data.get("run_validity"),
                    "coverage_quality": data.get("coverage_quality"),
                    "passed": ls.get("passed"),
                    "failed": ls.get("failed"),
                    "total": ls.get("total"),
                    "gaps": len(data.get("coverage_gaps") or []),
                }
            )
        rows.append(row)

    print(f"\n{'='*60}\nSMOKE SUMMARY\n{'='*60}")
    print(f"{'Story':<22} {'Validity':<26} {'Pass/Total':<12} {'Fail':<5} {'Gaps'}")
    for r in rows:
        pt = f"{r.get('passed','?')}/{r.get('total','?')}"
        print(
            f"{r['story']:<22} {str(r.get('run_validity','ERR')):<26} "
            f"{pt:<12} {str(r.get('failed','?')):<5} {r.get('gaps','?')}"
        )
    summary_path = OUTPUTS / "mentor-smoke-summary.json"
    summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote {summary_path}")
    return 0 if all(r.get("exit") == 0 for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
