"""Attestation Stage-1 — cascade is the authority; needles are diagnostic.

These tests encode the post-Stage-1 architectural invariant:

  Verdict = f(binding.attestation_mode, tc.attestation_mode, threat_class)

The legacy needles (``test_signals_missing_control``) never decide the
verdict; they only contribute a diagnostic hint when the cascade returns
UNCLASSIFIED.

Coverage:

  • Explicit binding stamps drive the verdict (binding wins).
  • Style-1 vs style-2 missing_control gives opposite verdicts on the
    same mode (driven by ``expected_status_code``).
  • UNCLASSIFIED produces ``inconclusive`` — no silent green / red.
  • Needles produce a *hint* on UNCLASSIFIED verdicts; they do NOT
    flip an explicit stamp.
  • Legacy ``test_signals_missing_control`` still returns True on gap-
    phrased tests (Stage 2 will delete the function entirely).
"""

from __future__ import annotations

from agents.attestation import (
    adversarial_verdict_on_fail,
    adversarial_verdict_on_pass,
    attestation_diagnostic_hint,
    infer_attestation_mode,
    stamp_attestation_mode,
)
# Aliased import — the function name starts with "test_" which makes pytest
# try to collect it as a test case when imported into a test module. Rename
# locally to disable that.
from agents.attestation import test_signals_missing_control as _signals_missing_control
from state import BackendEndpoint, SurfaceBinding, TestCase


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _register_binding(attestation_mode: str = "missing_control") -> SurfaceBinding:
    return SurfaceBinding(
        requirement_id="REQ-001",
        state="BACKEND_API",
        backend_endpoints=[BackendEndpoint(
            method="POST", path="/register",
            handler_file="routers/auth_router.py", handler_line=27,
        )],
        rationale="control absent in retrieval" if attestation_mode == "missing_control"
                  else "defense present in retrieval",
        confidence="high",
        attestation_mode=attestation_mode,
    )


def _adv_test(**kwargs) -> TestCase:
    base = dict(
        test_id="TC-001",
        title="adversarial test",
        action="POST /register",
        expected_result="some outcome",
        is_adversarial=True,
    )
    base.update(kwargs)
    return TestCase(**base)


# ─── Cascade precedence ───────────────────────────────────────────────────


def test_explicit_binding_stamp_wins_over_test_stamp():
    """binding.attestation_mode beats tc.attestation_mode."""
    binding = _register_binding("missing_control")
    tc = _adv_test(attestation_mode="defense_confirming")
    assert infer_attestation_mode(tc, binding) == "missing_control"


def test_test_stamp_used_when_binding_has_none():
    """tc.attestation_mode used when binding doesn't tag."""
    binding = SurfaceBinding(
        requirement_id="REQ-001", state="BACKEND_API",
        backend_endpoints=[BackendEndpoint(
            method="POST", path="/login", handler_file="routers/auth_router.py")],
        rationale="ordinary login flow", confidence="high",
    )
    tc = _adv_test(attestation_mode="defense_confirming")
    assert infer_attestation_mode(tc, binding) == "defense_confirming"


def test_threat_class_implies_defense_confirming():
    """DEFENSIVE_INVERTED + defense_kind implies defense_confirming."""
    binding = SurfaceBinding(
        requirement_id="REQ-001", state="BACKEND_API",
        backend_endpoints=[BackendEndpoint(
            method="POST", path="/register", handler_file="routers/auth_router.py")],
        rationale="length validator + EmailStr",
        confidence="high",
        threat_class="DEFENSIVE_INVERTED",
        defense_kind="INPUT_REJECTION",
        defense_assertion="POST /register returns 422 when email > 255",
    )
    tc = _adv_test()
    assert infer_attestation_mode(tc, binding) == "defense_confirming"


def test_unclassified_returns_none():
    """No binding mode, no test mode, no threat_class → UNCLASSIFIED."""
    tc = _adv_test()
    assert infer_attestation_mode(tc, None) is None


def test_stamp_writes_cascade_result_onto_test():
    binding = _register_binding("missing_control")
    tc = _adv_test()
    stamp_attestation_mode(tc, binding)
    assert tc.attestation_mode == "missing_control"


def test_stamp_leaves_non_adversarial_untouched():
    binding = _register_binding("missing_control")
    tc = _adv_test(is_adversarial=False)
    stamp_attestation_mode(tc, binding)
    assert tc.attestation_mode is None


# ─── Verdict — explicit stamps drive the outcome ─────────────────────────


def test_missing_control_style1_pass_is_vulnerable():
    """Style-1 missing_control: test expects unprotected status (401).
    Pytest pass = gap reproduced = vulnerable."""
    binding = _register_binding("missing_control")
    tc = _adv_test(
        title="No rate limit: 10 failed logins all return 401",
        action="POST /login",
        expected_status_code=401,
    )
    v, ev = adversarial_verdict_on_pass(tc, binding)
    assert v == "vulnerable"
    assert any("style-1" in e for e in ev)


def test_missing_control_style2_pass_is_resilient():
    """Style-2 missing_control: test expects enforcement status (429).
    Pytest pass = control unexpectedly fired = good news = resilient."""
    binding = _register_binding("missing_control")
    tc = _adv_test(
        title="Burst registers should return 429",
        action="POST /register",
        expected_status_code=429,
    )
    v, ev = adversarial_verdict_on_pass(tc, binding)
    assert v == "resilient"
    assert any("style-2" in e for e in ev)


def test_missing_control_style2_fail_is_vulnerable():
    """Style-2 missing_control: expected 429, got 201 (no rate limit).
    Pytest fail = gap reproduced = vulnerable."""
    binding = _register_binding("missing_control")
    tc = _adv_test(
        title="Burst registers should return 429",
        action="POST /register",
        expected_status_code=429,
    )
    v, ev = adversarial_verdict_on_fail(
        tc, "Expected status 429, got 201 at iteration 1/1", binding,
    )
    assert v == "vulnerable"
    assert any("style-2" in e for e in ev)


def test_missing_control_style1_fail_is_resilient():
    """Style-1 missing_control: expected unprotected 401, got something else.
    Control may actually exist after all → resilient (low confidence)."""
    binding = _register_binding("missing_control")
    tc = _adv_test(
        title="No rate limit: 10 failed logins all return 401",
        action="POST /login",
        expected_status_code=401,
    )
    v, _ = adversarial_verdict_on_fail(
        tc, "Expected status 401, got 429 at iteration 5/10", binding,
    )
    assert v == "resilient"


def test_defense_confirming_pass_is_resilient():
    binding = _register_binding("defense_confirming")
    tc = _adv_test(
        title="Reject overlong email at /register",
        action="POST /register",
        expected_status_code=422,
    )
    v, _ = adversarial_verdict_on_pass(tc, binding)
    assert v == "resilient"


def test_defense_confirming_fail_is_vulnerable():
    """Defense was supposed to hold; pytest fail means it didn't."""
    binding = _register_binding("defense_confirming")
    tc = _adv_test(
        title="Reject overlong email at /register",
        action="POST /register",
        expected_status_code=422,
    )
    v, _ = adversarial_verdict_on_fail(
        tc, "Expected status 422, got 201", binding,
    )
    assert v == "vulnerable"


# ─── The smoking gun — needles must not override explicit stamps ─────────


def test_explicit_defense_confirming_NOT_overridden_by_enumeration_title():
    """ARCHITECTURAL INVARIANT (Stage 1).

    Test title contains 'User Enumeration' → legacy needle matches gap.
    Test is explicitly stamped ``defense_confirming``.

    Pre-Stage-1 code returned vulnerable because needles overrode the
    stamp. Post-Stage-1 code returns resilient — the explicit stamp is
    the authority. If the binding is wrong, fix the Resolver tag; do
    NOT fight the symptom in the classifier.
    """
    tc = _adv_test(
        title="Duplicate registration returns 409 Conflict (User Enumeration)",
        action="POST /register",
        expected_status_code=409,
        attestation_mode="defense_confirming",
    )
    v, _ = adversarial_verdict_on_pass(tc)
    assert v == "resilient"


def test_explicit_missing_control_NOT_overridden_by_defensive_title():
    tc = _adv_test(
        title="Length validator rejects 1000-char email at /register",
        action="POST /register",
        expected_status_code=201,  # style-1: expects unprotected
        attestation_mode="missing_control",
    )
    v, _ = adversarial_verdict_on_pass(tc)
    assert v == "vulnerable"


# ─── UNCLASSIFIED behavior ────────────────────────────────────────────────


def test_unclassified_pass_is_inconclusive():
    tc = _adv_test(title="Some adversarial test", expected_status_code=200)
    v, ev = adversarial_verdict_on_pass(tc, binding=None)
    assert v == "inconclusive"
    assert any("UNCLASSIFIED" in e for e in ev)


def test_unclassified_fail_is_inconclusive():
    tc = _adv_test(title="Some adversarial test", expected_status_code=200)
    v, ev = adversarial_verdict_on_fail(tc, "Expected 200, got 500", binding=None)
    assert v == "inconclusive"
    assert any("UNCLASSIFIED" in e for e in ev)


def test_unclassified_with_gap_title_includes_diagnostic_hint():
    """Needles still surface a hint on UNCLASSIFIED verdicts — diagnostic
    only. The verdict stays inconclusive; the hint helps reviewers see
    what the test looked like it wanted to assert."""
    tc = _adv_test(
        title="GET /tasks/{task_id} fails to sanitize <script> tag in title",
        expected_status_code=200,
    )
    v, ev = adversarial_verdict_on_pass(tc)
    assert v == "inconclusive"
    assert any("diagnostic-hint" in e for e in ev)


# ─── Legacy diagnostic — needles function still works for telemetry ──────


def test_legacy_needles_still_detect_gap_phrasing():
    tc = _adv_test(title="No rate limit: 10 failed logins return 401 without 429")
    assert _signals_missing_control(tc) is True


def test_diagnostic_hint_returns_string_for_gap_test():
    tc = _adv_test(title="fails to sanitize HTML in title")
    assert attestation_diagnostic_hint(tc) is not None


def test_diagnostic_hint_returns_none_for_clean_test():
    tc = _adv_test(title="Reject email > 255 chars at /register")
    assert attestation_diagnostic_hint(tc) is None
