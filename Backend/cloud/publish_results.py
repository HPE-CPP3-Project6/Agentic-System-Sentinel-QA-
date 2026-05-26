"""Upload the run's artifacts to Cloud Storage with a structured manifest.

Phase-1 output layout in GCS:

    gs://<bucket>/runs/<run-id>/
        exec-demo.json                       # the run summary main.py dumped
        workspace/test_sentinel_api_generated.py
        container.log                        # optional, when --container-logs given
        index.json                           # manifest + lifted headline metrics

`index.json` is the front door — one URL that tells you the patches proposed,
posture, and where each artifact lives. Stakeholders read this; tooling
parses it. Phase 3 swaps to (or augments with) a Firestore record per run.

Env vars (entrypoint sets these; CLI flags override):
    SENTINEL_GCS_BUCKET             required for upload (omit to force dry-run)
    SENTINEL_RUN_ID                 default: UTC timestamp; in cloud, set to commit SHA
    SENTINEL_PUBLISH_DRY_RUN        "1" → print what would upload, touch nothing
    GOOGLE_APPLICATION_CREDENTIALS  standard ADC; Cloud Run picks up the SA automatically

Usage:
    python -m cloud.publish_results                                 # auto-discover, env-driven
    python -m cloud.publish_results --dry-run                       # local smoke
    python -m cloud.publish_results --run-id abc123 --bucket foo    # explicit

Exit codes:
    0  success (or successful dry-run)
    2  required input artifact missing
    3  GCS upload failed
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent


# --------------------------------------------------------------------------- #
# Discovery                                                                    #
# --------------------------------------------------------------------------- #


def _latest(pattern_dir: Path, glob: str) -> Optional[Path]:
    """Return the most recently modified file matching `glob` under `pattern_dir`."""
    if not pattern_dir.is_dir():
        return None
    matches = sorted(pattern_dir.glob(glob), key=lambda p: p.stat().st_mtime, reverse=True)
    return matches[0] if matches else None


def _latest_run_subdir(workspace_runs: Path) -> Optional[Path]:
    """Most recent run_<UTC>_utc directory under workspace/runs/."""
    if not workspace_runs.is_dir():
        return None
    candidates = [p for p in workspace_runs.iterdir() if p.is_dir() and p.name.startswith("run_")]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def discover_artifacts() -> Tuple[Optional[Path], Optional[Path]]:
    """Return (exec_demo_json, workspace_pytest_file) — either may be None.

    `outputs/` is at repo root (main.py writes there); workspace/runs/ is
    under Backend/ (security_compiler writes there).
    """
    exec_demo = _latest(_REPO_ROOT / "outputs", "exec-demo-*.json")
    workspace_runs = _BACKEND_ROOT / "workspace" / "runs"
    latest_run = _latest_run_subdir(workspace_runs)
    pytest_file = latest_run / "test_sentinel_api_generated.py" if latest_run else None
    if pytest_file and not pytest_file.is_file():
        pytest_file = None
    return exec_demo, pytest_file


# --------------------------------------------------------------------------- #
# Index summary — the headline read                                            #
# --------------------------------------------------------------------------- #


def _safe_load(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"_load_error": f"{type(exc).__name__}: {exc}"}


def build_index(
    *,
    run_id: str,
    exec_demo: Optional[Path],
    pytest_file: Optional[Path],
    container_log: Optional[Path],
    uploaded: List[Dict[str, str]],
    bucket: Optional[str],
) -> Dict[str, Any]:
    """Lift headline metrics out of exec-demo.json into a small front-door doc."""
    demo = _safe_load(exec_demo) if exec_demo else {}
    return {
        "schema_version": "1",
        "run_id": run_id,
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "bucket": bucket,
        "headline": {
            "story_id": demo.get("story_id"),
            "story_title": demo.get("story_title"),
            "pipeline_mode": demo.get("pipeline_mode"),
            "heal_attempts": demo.get("heal_attempts"),
            "test_suite_size": demo.get("test_suite_size"),
            "patches_proposed": len(demo.get("suggested_patches") or []),
            "security_posture": (demo.get("metadata") or {}).get("security_posture"),
            "logs_summary": demo.get("logs_summary"),
        },
        "artifacts": uploaded,
        "input_paths": {
            "exec_demo_json": str(exec_demo) if exec_demo else None,
            "pytest_file": str(pytest_file) if pytest_file else None,
            "container_log": str(container_log) if container_log else None,
        },
    }


# --------------------------------------------------------------------------- #
# Upload backends                                                              #
# --------------------------------------------------------------------------- #


def _make_gcs_client():
    """Lazy import so dry-run paths work without google-cloud-storage installed."""
    from google.cloud import storage  # type: ignore
    return storage.Client()


def _upload_one(
    client,
    bucket_name: str,
    src: Path,
    dest_blob: str,
    content_type: str,
    *,
    dry_run: bool,
) -> Dict[str, str]:
    gcs_uri = f"gs://{bucket_name}/{dest_blob}"
    size = src.stat().st_size if src.is_file() else 0
    if dry_run:
        print(
            f"[publish] DRY-RUN would upload {src} ({size} B) "
            f"→ {gcs_uri} (content_type={content_type})",
            file=sys.stderr,
        )
        return {"gcs_uri": gcs_uri, "size_bytes": str(size), "content_type": content_type}

    bucket = client.bucket(bucket_name)
    blob = bucket.blob(dest_blob)
    blob.content_type = content_type
    blob.upload_from_filename(str(src))
    print(f"[publish] uploaded {src.name} → {gcs_uri}", file=sys.stderr)
    return {"gcs_uri": gcs_uri, "size_bytes": str(size), "content_type": content_type}


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bucket",
        default=os.environ.get("SENTINEL_GCS_BUCKET", "").strip(),
        help="GCS bucket name (default: $SENTINEL_GCS_BUCKET). If empty, forces --dry-run.",
    )
    parser.add_argument(
        "--run-id",
        default=os.environ.get("SENTINEL_RUN_ID", "").strip()
        or _dt.datetime.now(_dt.timezone.utc).strftime("local-%Y%m%dT%H%M%SZ"),
        help="Run identifier (commit SHA in CI; UTC stamp locally).",
    )
    parser.add_argument("--exec-demo-json", type=Path, default=None)
    parser.add_argument("--workspace-pytest", type=Path, default=None,
                        help="Path to the generated test_sentinel_api_generated.py.")
    parser.add_argument("--container-logs", type=Path, default=None,
                        help="Optional file with full container stdout/stderr.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("SENTINEL_PUBLISH_DRY_RUN", "").strip() in ("1", "true", "yes"),
        help="Print what would upload; touch nothing.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    auto_demo, auto_pytest = discover_artifacts()
    exec_demo = args.exec_demo_json or auto_demo
    pytest_file = args.workspace_pytest or auto_pytest
    container_log = args.container_logs

    if exec_demo is None:
        print(
            "[publish] no exec-demo-*.json found under outputs/ — did main.py run?",
            file=sys.stderr,
        )
        return 2

    dry_run = args.dry_run or not args.bucket
    if dry_run and not args.bucket:
        print(
            "[publish] no --bucket / SENTINEL_GCS_BUCKET set → forcing dry-run",
            file=sys.stderr,
        )

    # Build the upload manifest (src path, dest blob name, content-type)
    plan: List[Tuple[Path, str, str]] = [
        (exec_demo, f"runs/{args.run_id}/exec-demo.json", "application/json"),
    ]
    if pytest_file is not None:
        plan.append(
            (pytest_file, f"runs/{args.run_id}/workspace/test_sentinel_api_generated.py",
             "text/x-python")
        )
    else:
        print(
            "[publish] no workspace test file found — skipping (pipeline may have "
            "produced an empty test_suite, or workspace/runs/ is gone)",
            file=sys.stderr,
        )
    if container_log is not None and container_log.is_file():
        plan.append((container_log, f"runs/{args.run_id}/container.log", "text/plain"))

    client = None if dry_run else _make_gcs_client()

    uploaded: List[Dict[str, str]] = []
    try:
        for src, dest_blob, ct in plan:
            uploaded.append(_upload_one(client, args.bucket, src, dest_blob, ct, dry_run=dry_run))
    except Exception as exc:  # noqa: BLE001 — surface any GCS error with context
        print(f"[publish] upload failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    # Always write the index LAST so partial uploads don't masquerade as complete.
    index = build_index(
        run_id=args.run_id,
        exec_demo=exec_demo,
        pytest_file=pytest_file,
        container_log=container_log,
        uploaded=uploaded,
        bucket=args.bucket or None,
    )
    index_blob = f"runs/{args.run_id}/index.json"
    index_payload = json.dumps(index, indent=2, default=str)

    if dry_run:
        print(
            f"[publish] DRY-RUN would write index.json ({len(index_payload)} B) "
            f"→ gs://{args.bucket or '<no-bucket>'}/{index_blob}",
            file=sys.stderr,
        )
        # Print the manifest to stdout in dry-run so callers can inspect it
        print(index_payload)
    else:
        bucket_obj = client.bucket(args.bucket)
        blob = bucket_obj.blob(index_blob)
        blob.content_type = "application/json"
        blob.upload_from_string(index_payload, content_type="application/json")
        index_uri = f"gs://{args.bucket}/{index_blob}"
        print(f"[publish] wrote index → {index_uri}", file=sys.stderr)
        # CONTRACT: last stdout line is the front-door URI so the entrypoint
        # can echo it into the container log / Cloud Logging.
        print(index_uri)

    return 0


if __name__ == "__main__":
    sys.exit(main())
