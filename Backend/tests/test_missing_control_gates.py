"""Regression tests for the two missing_control false-red fixes.

Fix B (surface_resolver): the Stage-3 third-path promotion is gated to
HEADER controls only, so non-header controls (input sanitization, etc.) are
not wrongly promoted to missing_control on a retrieval MISS.

Fix A (pytest_runner): on the pass path, a content-class missing_control
style-1 probe that passes on a success status with no body evidence the
payload survived is withheld as inconclusive, not asserted vulnerable.
"""

from __future__ import annotations

from agents.pytest_runner import _classify_adversarial_pass, _is_content_class_probe
from agents.surface_resolver import _HEADER_CONTROL_RE
from state import TestCase


# ─── Fix B — header-specific gate discriminator ──────────────────────────


def test_header_control_re_matches_header_tokens():
    for text in [
        "responses must include an X-Frame-Options header",
        "endpoint must set Content-Security-Policy",
        "HTTPS responses include Strict-Transport-Security",
        "X-Content-Type-Options: nosniff must be present",
        "the API should emit appropriate security headers",
        "response must carry a CSP header",
        "HSTS must be enforced on all responses",
    ]:
        assert _HEADER_CONTROL_RE.search(text), text


def test_header_control_re_ignores_non_header_controls():
    # These are the false-red triggers: real controls whose evidence the
    # header scan can't see. Stage-3 must NOT fire for them.
    for text in [
        "description must be HTML-sanitized to prevent stored XSS",
        "title is stripped of whitespace and rejected when blank",
        "search must use parameterized SQL to prevent injection",
        "GET /tasks/ returns a paginated list of the user's tasks",
        "login must resist brute-force attacks with rate limiting",
    ]:
        assert not _HEADER_CONTROL_RE.search(text), text


# ─── Fix A — pass-path body-evidence gate ────────────────────────────────


def _adv_tc(**kwargs) -> TestCase:
    base = dict(
        test_id="TC-A",
        title="probe",
        action="POST /tasks/",
        expected_result="created",
        expected_status_code=201,  # 2xx success → style-1
        is_adversarial=True,
        attestation_mode="missing_control",
    )
    base.update(kwargs)
    return TestCase(**base)


def test_content_probe_pass_without_body_evidence_is_inconclusive():
    # XSS content probe, expects 201, passes, no body captured on pass →
    # the gap is unconfirmed → inconclusive (not a confident "vulnerable").
    tc = _adv_tc(
        title="POST /tasks/ with XSS in description",
        forbidden_response_content=["<script>"],
        exploit_target="A03:2021",
    )
    v, ev = _classify_adversarial_pass(tc, detail="", binding=None)
    assert v == "inconclusive"
    assert any("unconfirmed" in e for e in ev)


def test_content_probe_pass_with_body_evidence_stays_vulnerable():
    # When the response body actually shows the forbidden fragment, the gap
    # IS confirmed → stays vulnerable.
    tc = _adv_tc(
        title="POST /tasks/ with XSS in description",
        forbidden_response_content=["<script>alert(1)</script>"],
        exploit_target="A03:2021",
    )
    detail = 'response: {"description": "<script>alert(1)</script>clean text"}'
    v, ev = _classify_adversarial_pass(tc, detail=detail, binding=None)
    assert v == "vulnerable"


def test_behavioural_probe_pass_stays_vulnerable():
    # Rate-limit style-1 probe: no forbidden content, no A03 tag. A pass on
    # the unprotected status IS the evidence (no throttle) → stays vulnerable.
    tc = _adv_tc(
        title="100 rapid POST /login attempts are not throttled",
        action="POST /login",
        expected_status_code=200,
        owasp_category="A04:2021",
        exploit_target="A04:2021",
    )
    v, ev = _classify_adversarial_pass(tc, detail="", binding=None)
    assert v == "vulnerable"


def test_defense_confirming_pass_is_resilient_unchanged():
    tc = _adv_tc(attestation_mode="defense_confirming")
    v, ev = _classify_adversarial_pass(tc, detail="", binding=None)
    assert v == "resilient"


def test_is_content_class_probe_signals():
    assert _is_content_class_probe(_adv_tc(forbidden_response_content=["x"]))
    assert _is_content_class_probe(_adv_tc(exploit_target="A03:2021"))
    assert _is_content_class_probe(_adv_tc(owasp_category="A03:2021-Injection"))
    assert not _is_content_class_probe(
        _adv_tc(owasp_category="A04:2021", exploit_target="A04:2021")
    )
