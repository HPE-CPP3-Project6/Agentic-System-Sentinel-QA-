"""Stage-3 — honest header attestation tests.

These cover the false-green pattern observed on run r_7f0025d2:

  • The Generator emitted tests titled "GET /health includes
    X-Frame-Options" that only asserted status_code == 200. The TestCase
    schema had no `required_response_headers` field, so the title's
    semantic claim never reached the pytest harness.
  • The Resolver tagged the bindings DEFENSIVE_NORMAL → defense_confirming
    because the routes existed in retrieval — even though the actual
    security control (the header middleware) did NOT.

Stage 3 adds two interlocking fixes:

  1. Generator post-validation DROPS tests whose title claims a header
     and whose required_response_headers dict is empty.
  2. Resolver third-path promotion flips BACKEND_API + Critic-risk +
     control-absent bindings to missing_control, so headers stories
     produce style-2 gap tests that fail when the header is missing.
"""

from __future__ import annotations

from agents.generator import _header_claim_without_assertion
from agents.surface_resolver import (
    _retrieval_shows_header_defense,
    _signals_missing_security_control,
)
from state import BackendEndpoint, SurfaceBinding, TestCase


def _tc(**kwargs) -> TestCase:
    base = dict(
        test_id="TC-001",
        title="test",
        action="GET /health",
        expected_result="ok",
        expected_status_code=200,
        is_adversarial=True,
    )
    base.update(kwargs)
    return TestCase(**base)


def _binding(**kwargs) -> SurfaceBinding:
    base = dict(
        requirement_id="REQ-001",
        state="BACKEND_API",
        backend_endpoints=[BackendEndpoint(
            method="GET", path="/health",
            handler_file="main.py", handler_line=100,
        )],
        rationale="ordinary endpoint",
        confidence="high",
    )
    base.update(kwargs)
    return SurfaceBinding(**base)


# ─── Generator post-validation: drop header-claim with empty assertion ────


def test_header_claim_with_empty_headers_is_dropped():
    """The false-green smoking gun: title claims a header, dict is empty."""
    tc = _tc(title="GET /health includes X-Frame-Options: DENY or SAMEORIGIN header")
    reason = _header_claim_without_assertion(tc)
    assert reason is not None
    assert "header-claim coverage gap" in reason


def test_header_claim_with_populated_headers_is_accepted():
    tc = _tc(
        title="GET /health includes X-Frame-Options: DENY or SAMEORIGIN header",
        required_response_headers={"x-frame-options": None},
    )
    assert _header_claim_without_assertion(tc) is None


def test_non_header_test_with_empty_headers_is_accepted():
    """Functional / non-header tests must NOT be dropped."""
    tc = _tc(title="GET /tasks/ returns 200 OK with paginated data")
    assert _header_claim_without_assertion(tc) is None


def test_csp_directive_check_token_triggers_drop():
    tc = _tc(title="Successful login response CSP header includes 'default-src' directive")
    assert _header_claim_without_assertion(tc) is not None


def test_hsts_check_token_triggers_drop():
    tc = _tc(title="HTTPS responses include strict-transport-security header")
    assert _header_claim_without_assertion(tc) is not None


def test_referrer_policy_check_token_triggers_drop():
    tc = _tc(title="Response includes Referrer-Policy header")
    assert _header_claim_without_assertion(tc) is not None


def test_x_content_type_options_check_token_triggers_drop():
    tc = _tc(title="GET /health includes X-Content-Type-Options: nosniff header")
    assert _header_claim_without_assertion(tc) is not None


def test_csp_value_match_accepted():
    tc = _tc(
        title="CSP header includes 'default-src' directive",
        required_response_headers={"content-security-policy": "default-src"},
    )
    assert _header_claim_without_assertion(tc) is None


# ─── Resolver helper: missing-control regex picks up header tokens ───────


def test_missing_control_regex_matches_x_frame_options():
    text = "The requirement specifies an X-Frame-Options header on responses"
    assert _signals_missing_security_control(text, []) is True


def test_missing_control_regex_matches_csp():
    text = "Responses must include a Content-Security-Policy header"
    assert _signals_missing_security_control(text, []) is True


def test_missing_control_regex_matches_security_header_phrase():
    text = "The endpoint should emit appropriate security headers"
    assert _signals_missing_security_control(text, []) is True


def test_missing_control_regex_does_not_match_plain_business_text():
    text = "GET /tasks/ returns a paginated list of tasks owned by the user"
    assert _signals_missing_security_control(text, []) is False


# ─── Resolver helper: positive defense evidence in retrieval ─────────────


def test_retrieval_shows_header_defense_with_middleware_token():
    b = _binding(rationale="main.py calls app.add_middleware(SecurityHeadersMiddleware)")
    assert _retrieval_shows_header_defense(b) is True


def test_retrieval_shows_header_defense_with_response_headers_token():
    b = _binding(rationale="The handler explicitly sets response.headers['X-Frame-Options'] = 'DENY'")
    assert _retrieval_shows_header_defense(b) is True


def test_retrieval_shows_header_defense_returns_false_when_no_evidence():
    b = _binding(rationale="The /health endpoint is defined in main.py and returns {'status': 'ok'}")
    assert _retrieval_shows_header_defense(b) is False


def test_retrieval_check_examines_grounding_refs_too():
    """If the grounding ref names a known middleware file, count it."""
    b = _binding(
        rationale="ordinary handler",
        grounding_refs=["middleware.py:1-30 add_middleware(SecurityHeadersMiddleware)"],
    )
    assert _retrieval_shows_header_defense(b) is True
