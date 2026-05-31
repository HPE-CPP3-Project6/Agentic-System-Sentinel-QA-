"""Run the Sentinel-QA API shim.

Usage (from Backend/):
    python run_shim.py

Dev reload watches only ``shim/`` — not ``workspace/`` where pytest scripts
and run artifacts are written (those used to trigger mid-run reloads).
"""

from __future__ import annotations

from pathlib import Path

import uvicorn

_BACKEND_DIR = Path(__file__).resolve().parent
_SHIM_DIR = _BACKEND_DIR / "shim"

if __name__ == "__main__":
    uvicorn.run(
        "shim.app:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        # Only reload when shim source changes — not pipeline output under workspace/.
        reload_dirs=[str(_SHIM_DIR)],
    )
