"""Surface Resolver — missing-control / offensive-security promotion."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.surface_resolver import (
    _promote_missing_control_binding,
    _recover_not_implemented_binding,
    _validate_threat_class,
)
from state import SurfaceBinding, ValidatedRequirement

REPO_ROOT = Path(__file__).resolve().parent.parent / "repo_cache"


def _login_binding(**updates) -> SurfaceBinding:
    base = SurfaceBinding(
        requirement_id="REQ-001",
        state="BACKEND_API",
        threat_class="DEFENSIVE_INVERTED",
        defense_kind="INPUT_REJECTION",
        defense_assertion="POST /login returns 429 after 10 failures",
        anti_pattern_summary="unlimited login retries",
        backend_endpoints=[],
        grounding_refs=["routers/auth_router.py:85-111"],
        rationale=(
            "The POST /login endpoint in routers/auth_router.py does not contain "
            "any logic for tracking failed login attempts, applying rate limits, "
            "or returning HTTP 429."
        ),
        confidence="high",
    )
    return base.model_copy(update=updates)


def _brute_force_req() -> ValidatedRequirement:
    return ValidatedRequirement(
        requirement_id="REQ-001",
        statement="Login must resist brute-force attacks.",
        ambiguity_score=0.0,
        acceptance_criteria=[
            "After 10 failed POST /login attempts, the next attempt must return HTTP 429.",
        ],
    )


@pytest.mark.skipif(not REPO_ROOT.is_dir(), reason="repo_cache not present")
def test_defensive_inverted_without_defense_promotes_post_login():
    binding = _login_binding()
    req = _brute_force_req()
    out = _validate_threat_class(
        binding,
        ["A04:2021-Insecure Design"],
        req=req,
        repo_roots=[REPO_ROOT],
    )
    assert out.state == "BACKEND_API"
    assert out.attestation_mode == "missing_control"
    assert out.threat_class is None
    assert any(ep.method == "POST" and "/login" in ep.path for ep in out.backend_endpoints)


@pytest.mark.skipif(not REPO_ROOT.is_dir(), reason="repo_cache not present")
def test_not_implemented_with_auth_grounding_recovered():
    binding = _login_binding(state="NOT_IMPLEMENTED", threat_class=None)
    req = _brute_force_req()
    out = _recover_not_implemented_binding(
        binding, req, ["A04:2021"], [REPO_ROOT],
    )
    assert out.state == "BACKEND_API"
    assert out.attestation_mode == "missing_control"
    assert out.backend_endpoints


@pytest.mark.skipif(not REPO_ROOT.is_dir(), reason="repo_cache not present")
def test_promote_returns_none_without_security_signal():
    binding = _login_binding(
        rationale="Dashboard shows user email after login.",
    )
    assert _promote_missing_control_binding(binding, None, [], [REPO_ROOT]) is None
