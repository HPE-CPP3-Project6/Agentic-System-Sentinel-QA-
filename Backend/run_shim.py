"""Run the Sentinel-QA API shim.

Usage (from Backend/):
    python run_shim.py
    uvicorn shim.app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import uvicorn

if __name__ == "__main__":
    uvicorn.run("shim.app:app", host="0.0.0.0", port=8080, reload=True)
