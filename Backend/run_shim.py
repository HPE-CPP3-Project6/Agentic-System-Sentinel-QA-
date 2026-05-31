"""Run the Sentinel-QA API shim.

Usage (from Backend/):
    python run_shim.py

IMPORTANT — launch the shim THIS way, not via a raw `uvicorn shim.app:app
--reload`. The pipeline writes the generated pytest file
(`test_sentinel_api_generated.py`) and run state into `Backend/workspace/`
MID-RUN. The default uvicorn `--reload` watches the whole working directory,
so that write triggers a reload, which kills the worker thread running the
pipeline — the run dies right after the compile phase and the UI hangs.

This launcher prevents that two ways (belt + suspenders):
  1. reload_dirs   — watch ONLY shim/ source, never workspace/.
  2. reload_excludes — even if the watch set is widened, never reload on
     writes under workspace/, outputs/, chroma_data/, phase_bridge_data/, or
     on generated .py/.json/.db/.log files.

Trade-off: edits to pipeline source (agents/, database/, …) do NOT hot-reload
the shim — restart it manually after changing those. That's deliberate: a
narrow watch set is what keeps a long run from being torn down by its own
output.
"""

from __future__ import annotations

from pathlib import Path

import uvicorn

_BACKEND_DIR = Path(__file__).resolve().parent
_SHIM_DIR = _BACKEND_DIR / "shim"

# Defense-in-depth: never reload on pipeline output, regardless of watch set.
_RELOAD_EXCLUDES = [
    "*/workspace/*",
    "workspace/*",
    "*/outputs/*",
    "*/chroma_data/*",
    "*/chroma_models_cache/*",
    "*/phase_bridge_data/*",
    "*/repo_cache/*",
    "test_sentinel_api_generated.py",
    "*.json",
    "*.log",
    "*.db",
    "*.sqlite3",
]

if __name__ == "__main__":
    uvicorn.run(
        "shim.app:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        # Watch ONLY shim source — not pipeline output under workspace/.
        reload_dirs=[str(_SHIM_DIR)],
        reload_excludes=_RELOAD_EXCLUDES,
    )
