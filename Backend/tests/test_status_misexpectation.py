"""Status-misexpectation guard — a 4xx rejection is not a vulnerability.

Encodes the r_e533db86 false-positive class: the Generator's adversarial
acceptable-status lists omitted 422 (FastAPI's standard Pydantic rejection),
so tests where the app CORRECTLY rejected the attack flipped to "vulnerable"
under defense_confirming (5/5 of the run's vulnerable verdicts; the Healer
simultaneously called the same failures test defects).

Invariants pinned here:

  • defense_confirming + ANY-of assertion fail + actual 4xx rejection +
    no body leak → resilient (misexpectation, not vulnerability).
  • Body leak evidence still wins — a 4xx that leaks forbidden content
    stays vulnerable.
  • Exploit-success statuses (e.g. 200 on POST /login) are never treated
    as rejections.
  • missing_control style-2 probes are exempt — their fail condition is
    the enforcement status never firing, regardless of rejection shape.
  • Compiler signature lists now include 422 for non-missing_control
    adversarial tests.
"""

from __future__ import annotations

from agents.pytest_runner import (
    _body_evidence_says_vulnerable,
    _classify_adversarial_failure,
    _is_validation_error_rejection,
    _rejection_says_neutralized,
)
from agents.security_compiler import _acceptable_status_codes_for_adversarial
from state import BackendEndpoint, SurfaceBinding, TestCase


# ─── Fixtures ─────────────────────────────────────────────────────────────


def _binding(mode: str = "defense_confirming", path: str = "/register") -> SurfaceBinding:
    return SurfaceBinding(
        requirement_id="REQ-001",
        state="BACKEND_API",
        backend_endpoints=[BackendEndpoint(
            method="POST", path=path,
            handler_file="routers/auth_router.py", handler_line=27,
        )],
        rationale="defense present in retrieval",
        confidence="high",
        attestation_mode=mode,
    )


def _adv_test(**kwargs) -> TestCase:
    base = dict(
        test_id="TC-001",
        title="Registration rejects weak password",
        action="POST /register with weak password",
        expected_result="rejection",
        is_adversarial=True,
    )
    base.update(kwargs)
    return TestCase(**base)


_DETAIL_422 = (
    "AssertionError: Adversarial test expected ANY of [200, 400, 401, 413] "
    "(attack neutralized), got 422 at iteration 1/1 — excerpt: "
    '{"detail":[{"type":"string_too_short","loc":["body","password"]}]}'
)

_DETAIL_200 = (
    "AssertionError: Adversarial test expected ANY of [401, 403, 429] "
    "(attack neutralized), got 200 at iteration 1/1 — excerpt: "
    '{"access_token": "eyJ..."}'
)


# ─── Guard unit behavior ──────────────────────────────────────────────────


def test_422_rejection_detected_as_neutralized():
    tc = _adv_test()
    assert _rejection_says_neutralized(tc, _DETAIL_422) == 422


def test_200_is_not_a_rejection():
    tc = _adv_test()
    assert _rejection_says_neutralized(tc, _DETAIL_200) is None


def test_non_adv_assertion_message_does_not_match():
    tc = _adv_test()
    detail = "AssertionError: Expected status 201, got 422"
    assert _rejection_says_neutralized(tc, detail) is None


def test_login_200_never_counts_as_rejection_even_in_4xx_range():
    # Sanity: only 4xx can be a rejection — exploit-success mapping is a
    # second gate on top, tested via the classifier below.
    tc = _adv_test(action="POST /login with SQLi username")
    assert _rejection_says_neutralized(tc, _DETAIL_200) is None


# ─── Classifier integration ───────────────────────────────────────────────


def test_defense_confirming_422_rejection_is_resilient():
    """The r_e533db86 false positive — now resilient with explicit evidence."""
    tc = _adv_test()
    binding = _binding("defense_confirming")
    verdict, evidence = _classify_adversarial_failure(tc, _DETAIL_422, binding)
    assert verdict == "resilient"
    assert any("misexpectation" in e for e in evidence)


def test_defense_confirming_422_validation_envelope_keyword_is_resilient():
    """A forbidden keyword that only matches the Pydantic 422 envelope's
    structural fields (here the error `type` 'string_too_short') is NOT a
    leak — the attack was rejected at the validation layer. Resilient."""
    tc = _adv_test(forbidden_response_content=["string_too_short"])
    binding = _binding("defense_confirming")
    verdict, _ = _classify_adversarial_failure(tc, _DETAIL_422, binding)
    assert verdict == "resilient"


def test_defense_confirming_genuine_4xx_leak_stays_vulnerable():
    """A real leaked token in a NON-validation 4xx body (plain detail string,
    not a {loc/type/msg} envelope) is genuine body evidence → vulnerable."""
    tc = _adv_test(forbidden_response_content=["SQLSTATE"])
    binding = _binding("defense_confirming")
    detail = 'got 400 — excerpt: {"detail":"DB error: SQLSTATE[42000] near SELECT"}'
    verdict, _ = _classify_adversarial_failure(tc, detail, binding)
    assert verdict == "vulnerable"


def test_defense_confirming_200_stays_vulnerable():
    tc = _adv_test()
    binding = _binding("defense_confirming")
    verdict, _ = _classify_adversarial_failure(tc, _DETAIL_200, binding)
    assert verdict == "vulnerable"


def test_missing_control_style2_not_rescued_by_422():
    """Style-2 probe (expects 429 enforcement): a 422 rejection is NOT the
    throttle firing — the verdict must stay vulnerable."""
    tc = _adv_test(expected_status_code=429, action="POST /login burst")
    binding = _binding("missing_control", path="/login")
    detail = (
        "AssertionError: Adversarial test expected ANY of [429] "
        "(attack neutralized), got 422 at iteration 1/1"
    )
    verdict, _ = _classify_adversarial_failure(tc, detail, binding)
    assert verdict == "vulnerable"


# ─── Compiler layer ───────────────────────────────────────────────────────


def test_compiler_adds_422_to_signature_lists():
    tc = _adv_test(
        owasp_category="A07:2021-Identification and Authentication Failures",
        expected_status_code=401,
        attestation_mode="defense_confirming",
    )
    codes = _acceptable_status_codes_for_adversarial(tc)
    assert 422 in codes


def test_compiler_keeps_missing_control_strict():
    tc = _adv_test(
        owasp_category="A07:2021-Identification and Authentication Failures",
        expected_status_code=429,
        attestation_mode="missing_control",
    )
    codes = _acceptable_status_codes_for_adversarial(tc)
    assert 422 not in codes


# ─── Body-evidence: validation-envelope false positive ─────────────────────
# r_274ae9ee: an oversized-email test had forbidden_response_content=["email"].
# The app correctly rejected with 422, whose Pydantic body echoes
# {"loc":["body","email"]}. The B2 keyword tier matched "email" inside that
# structural envelope and false-flagged the test vulnerable. A field name in a
# 4xx validation rejection is not a leak.

_VALIDATION_422 = (
    'got 422 — excerpt: {"detail":[{"type":"string_too_long",'
    '"loc":["body","email"],"msg":"value too long"}]}'
)


def test_validation_envelope_keyword_is_not_a_leak():
    tc = _adv_test(forbidden_response_content=["email", "password"])
    assert _body_evidence_says_vulnerable(tc, _VALIDATION_422) is False


def test_real_leak_on_2xx_success_still_fires():
    tc = _adv_test(action="GET /users", forbidden_response_content=["hashed_password"])
    detail = 'got 200 — excerpt: {"email":"v@x.com","hashed_password":"$2b$.."}'
    assert _body_evidence_says_vulnerable(tc, detail) is True


def test_stack_trace_on_500_still_fires():
    tc = _adv_test(forbidden_response_content=["Traceback"])
    detail = "got 500 — excerpt: Traceback (most recent call last): sqlalchemy.exc"
    assert _body_evidence_says_vulnerable(tc, detail) is True


def test_validation_rejection_helper():
    assert _is_validation_error_rejection(422, _VALIDATION_422) is True
    assert _is_validation_error_rejection(200, _VALIDATION_422) is False
    # 4xx but not a validation envelope (plain detail string) — not suppressed.
    assert _is_validation_error_rejection(400, 'got 400 excerpt: {"detail":"bad"}') is False
