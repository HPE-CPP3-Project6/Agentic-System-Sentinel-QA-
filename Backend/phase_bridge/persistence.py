"""Save and load Phase 1 (PRE_CODE) output so Phase 2 can consume it."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

BRIDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "phase_bridge_data")


def _bridge_path(story_id: str) -> str:
    os.makedirs(BRIDGE_DIR, exist_ok=True)
    return os.path.join(BRIDGE_DIR, f"{story_id}_phase1.json")


def save_phase1(state) -> str:
    """Serialize Phase 1 outputs from ProjectState to a JSON file.
    Returns the file path written."""
    payload: Dict[str, Any] = {
        "story_id": state.story_id,
        "pipeline_mode": state.pipeline_mode,
        "phase1_risk_ids": [r.owasp_id for r in state.security_risks],
        "design_contracts": [c.model_dump() for c in state.design_contracts],
        "security_checklist": [i.model_dump() for i in state.security_checklist],
        "validated_requirements": [r.model_dump() for r in state.validated_requirements],
    }
    path = _bridge_path(state.story_id or "unknown")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[phase_bridge] Phase 1 saved → {path}")
    return path


def load_phase1(story_id: str) -> Dict[str, Any]:
    """Load Phase 1 output for a given story_id.
    Returns empty dict if no Phase 1 data exists yet."""
    path = _bridge_path(story_id)
    if not os.path.exists(path):
        print(f"[phase_bridge] No Phase 1 data found for story '{story_id}'")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"[phase_bridge] Phase 1 loaded ← {path}")
    return data