"""Shared adversarial attestation semantics — single source of truth.

ARCHITECTURE (Stage 1 of the attestation refactor)
==================================================

`attestation_mode` is a property of the BINDING, not the test. The Resolver
classifies each requirement's binding as ``missing_control`` (control
absent in code, gap-attestation needed) or ``defense_confirming`` (defense
present, verify it holds). The Generator inherits the binding's mode onto
each adversarial TestCase. The Classifier (pytest_runner) reads the
stamped value and decides the verdict. Title / expected_result needles
NEVER drive the verdict — they only contribute diagnostic evidence when
the cascade returned UNCLASSIFIED.

CASCADE (highest precedence first)
----------------------------------
    binding.attestation_mode          # Resolver tagged the binding
    tc.attestation_mode               # Generator emitted via OUTPUT SCHEMA
    binding.threat_class implies it   # DEFENSIVE_INVERTED + defense_kind
                                      #   → defense_confirming
    None                              # UNCLASSIFIED — verdict=inconclusive

UNCLASSIFIED is an explicit sentinel, not a silent default. Tests that
reach the Classifier UNCLASSIFIED are surfaced honestly as
``inconclusive`` (no fake green light) and counted in a separate
``unclassified`` posture bucket. The dashboard shows this count
prominently so the resilience % is never inflated by misclassification.

VERDICT TABLE
-------------
    | binding/test mode    | pytest pass     | pytest fail            |
    |----------------------|-----------------|------------------------|
    | missing_control      | (see style)     | (see style)            |
    |   style-1            | vulnerable      | resilient              |
    |   style-2            | resilient       | vulnerable             |
    | defense_confirming   | resilient       | vulnerable             |
    | None (UNCLASSIFIED)  | inconclusive    | inconclusive           |

Style-1 vs style-2 for missing_control:
    Style-1: test expects the unprotected status (e.g. 401 in burst).
             Pass = gap reproduced = vulnerable.
    Style-2: test expects the enforcement status (e.g. 429, 423, 400 anti-
             enum on /register). Fail = expected control didn't fire =
             vulnerable.

The split is driven entirely by ``tc.expected_status_code`` via
``_is_style_2_design`` — no string matching.

NEEDLES (legacy)
----------------
``test_signals_missing_control`` survives as a DIAGNOSTIC helper only.
``attestation_diagnostic_hint`` returns a short string that the
Classifier attaches to the evidence list of UNCLASSIFIED verdicts so a
reviewer can see what the test *looked like* it wanted to assert — but
the verdict stays ``inconclusive`` until the Resolver or Generator
provides an explicit stamp. Stage 2 will delete the needles entirely
once the Stage-1 architecture stabilises.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from state import SurfaceBinding, TestCase


# ─── Diagnostic-only needles (Stage 2 will delete these) ──────────────────
#
# Kept here for ``attestation_diagnostic_hint``. NEVER consulted by the
# verdict cascade. If you find yourself adding a new needle, ask first
# whether the Resolver could have tagged the binding instead — that's the
# correct place to fix the misclassification.

_GAP_TITLE_NEEDLES = (
    "no rate limit",
    "without 429",
    "do not trigger 429",
    "not trigger 429",
    "succeed without 429",
    "no retry-after",
    "allowed (no rate limit",
    "not 429",
    "does not return 429",
    "no account lockout",
    "no lockout",
    "without throttl",
    "fails to sanitize",
    "fails to strip",
    "does not sanitize",
    "does not strip",
    "without sanitiz",
    "no sanitiz",
    "unsanitized",
    "persist unsanitized",
    "persists unsanitized",
    "literal <script",
    "contains <script",
    "contains <iframe",
    "onerror=",
    "no security header",
    "missing content-security-policy",
    "missing x-frame-options",
    "user enumeration",
    "account enumeration",
    "email enumeration",
    "enumerat",
    "409 conflict",
    "already exists",
    "already registered",
    "reveals email",
    "duplicate registration",
    "duplicate email",
)

_GAP_EXPECTED_NEEDLES = (
    "no 429",
    "not 429",
    "no throttl",
    "no lockout",
    "not locked",
    "no rate limit",
    "no <script",
    "not sanitized",
    "without sanitiz",
    "tags not removed",
    "markup not stripped",
    "html not stripped",
    "header absent",
    "not present in response headers",
    "not 409",
    "no 409",
    "must not return 409",
    "generic error",
    "generic body",
    "already exists",
    "already registered",
)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _action_targets_register(tc: TestCase) -> bool:
    blob = f"{tc.action or ''} {tc.title or ''}".lower()
    return "/register" in blob or "post /register" in blob


# HTTP codes that represent the ENFORCEMENT firing — used to detect a
# style-2 missing_control test. The set is intentionally small (the
# defenses we actually attest) so it cannot match by accident.
_ENFORCEMENT_CODES = frozenset({429, 423})


def _is_style_2_design(tc: TestCase) -> bool:
    """True iff the test was authored to assert the enforcement status.

    Style-2 tests expect a 4xx that proves the control fired (429 throttle,
    423 lockout, 400 anti-enumeration on /register). Pytest pass on a
    style-2 test means the defense actually exists; pytest fail means the
    expected enforcement never happened.

    Detection is purely structural — driven by
    ``tc.expected_status_code`` plus the /register anti-enum special case.
    No title strings.
    """
    esc = tc.expected_status_code
    if esc in _ENFORCEMENT_CODES:
        return True
    # Anti-enumeration on /register: AC requires a generic 400 rather than
    # the giveaway 409 + email-exists body. This is the only place the
    # /register-aware heuristic survives.
    if esc == 400 and _action_targets_register(tc):
        return True
    return False


_ACTUAL_STATUS_RE = re.compile(r"got\s+(\d{3})\b")


def _actual_status_from_detail(detail: str) -> Optional[int]:
    """Extract the actual HTTP status from a pytest assertion-failure
    detail string. Returns None when the detail does not name a status."""
    if not detail:
        return None
    m = _ACTUAL_STATUS_RE.search(detail)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def test_signals_missing_control(tc: TestCase) -> bool:
    """LEGACY DIAGNOSTIC — returns True if a test *looks like* a gap test.

    Kept for ``attestation_diagnostic_hint`` and the unit tests that
    document the legacy heuristic. NEVER consulted by the verdict
    cascade. Will be deleted in Stage 2.
    """
    title = (tc.title or "").lower()
    action = (tc.action or "").lower()
    if any(n in title for n in _GAP_TITLE_NEEDLES):
        return True
    if "sanitize" in action and any(
        w in title for w in ("fail", "does not", "without", "no ", "not ")
    ):
        return True
    expected = (tc.expected_result or "").lower()
    if any(n in expected for n in _GAP_EXPECTED_NEEDLES):
        return True
    rationale = (tc.coverage_rationale or "").lower()
    if "missing-control" in rationale:
        return True
    if "rule 4" in rationale and "gap" in rationale:
        return True
    return False


def attestation_diagnostic_hint(tc: TestCase) -> Optional[str]:
    """Short string for the evidence list when verdict is UNCLASSIFIED.

    Tells the reviewer what the test *looked like* it wanted to assert,
    without using that signal to decide the verdict. None when no hint
    is detectable.
    """
    if test_signals_missing_control(tc):
        return "diagnostic-hint: test phrasing matches missing-control gap"
    return None


# ─── Cascade ──────────────────────────────────────────────────────────────


def infer_attestation_mode(
    tc: TestCase,
    binding: Optional[SurfaceBinding] = None,
) -> Optional[str]:
    """Pure cascade — returns the explicit attestation_mode or None.

    Precedence (first match wins):
      1. ``binding.attestation_mode`` — Resolver-stamped.
      2. ``tc.attestation_mode``      — Generator-emitted via OUTPUT SCHEMA.
      3. DEFENSIVE_INVERTED + defense_kind — implies defense_confirming.
      4. None — UNCLASSIFIED.

    NEVER consults needles. UNCLASSIFIED is an honest output, not a bug.
    """
    if binding is not None and binding.attestation_mode:
        return binding.attestation_mode
    if tc.attestation_mode:
        return tc.attestation_mode
    if (
        binding is not None
        and binding.threat_class == "DEFENSIVE_INVERTED"
        and binding.defense_kind is not None
    ):
        return "defense_confirming"
    return None


def stamp_attestation_mode(
    tc: TestCase,
    binding: Optional[SurfaceBinding] = None,
) -> None:
    """Write the cascade result onto the TestCase.

    Idempotent — calling twice with the same binding produces the same
    value. Called by Generator post-LLM and (defensively) by pytest_runner
    just before classification.

    Non-adversarial tests are left untouched; attestation_mode is only
    meaningful when ``is_adversarial`` is True.
    """
    if not tc.is_adversarial:
        return
    tc.attestation_mode = infer_attestation_mode(tc, binding)


# ─── Verdict functions ────────────────────────────────────────────────────


def adversarial_verdict_on_pass(
    tc: TestCase,
    binding: Optional[SurfaceBinding] = None,
) -> Tuple[str, List[str]]:
    """Return (verdict, evidence) when pytest reports the adversarial test
    as ``passed``.

    Decision is driven entirely by the cascade. The needles never override.
    """
    mode = infer_attestation_mode(tc, binding)

    if mode == "missing_control":
        if _is_style_2_design(tc):
            # Style-2: test expected the ENFORCEMENT status; pytest pass
            # means the control DID fire. Good news — defense actually
            # exists despite Resolver tagging missing_control.
            return (
                "resilient",
                [
                    "attestation_mode=missing_control (style-2) — pass means "
                    f"expected enforcement status {tc.expected_status_code} "
                    "fired; control is unexpectedly present"
                ],
            )
        # Style-1: test expected the UNPROTECTED status; pytest pass means
        # the gap was reproduced.
        return (
            "vulnerable",
            [
                "attestation_mode=missing_control (style-1) — pass confirms "
                "the documented weakness (Rule 4)"
            ],
        )

    if mode == "defense_confirming":
        return (
            "resilient",
            ["attestation_mode=defense_confirming — defense assertions held"],
        )

    # UNCLASSIFIED — return inconclusive with a diagnostic hint.
    hint = attestation_diagnostic_hint(tc)
    evidence = ["UNCLASSIFIED — Resolver did not tag binding and Generator did not emit attestation_mode"]
    if hint:
        evidence.append(hint)
    return ("inconclusive", evidence)


def adversarial_verdict_on_fail(
    tc: TestCase,
    detail: str,
    binding: Optional[SurfaceBinding] = None,
) -> Tuple[str, List[str]]:
    """Return (verdict, evidence) when pytest reports the adversarial test
    as ``failed``.

    Decision is driven entirely by the cascade. The needles never override.
    """
    mode = infer_attestation_mode(tc, binding)

    if mode == "missing_control":
        if _is_style_2_design(tc):
            # Style-2: test expected the ENFORCEMENT status; pytest fail
            # means the expected control did NOT fire. Gap reproduced.
            actual = _actual_status_from_detail(detail)
            hint = (
                "anti-enumeration (generic 400) missing"
                if tc.expected_status_code == 400 and _action_targets_register(tc)
                else "rate limit / lockout missing"
            )
            evidence = [
                f"attestation_mode=missing_control (style-2) — expected "
                f"enforcement status {tc.expected_status_code}, "
                f"got {actual if actual is not None else '?'} ({hint})"
            ]
            return ("vulnerable", evidence)
        # Style-1: test expected the UNPROTECTED status; pytest fail means
        # the app returned something different — control may actually be
        # present. Good news.
        return (
            "resilient",
            [
                "attestation_mode=missing_control (style-1) — fail means the "
                "expected unprotected response was NOT observed; control may "
                "be present after all"
            ],
        )

    if mode == "defense_confirming":
        return (
            "vulnerable",
            ["attestation_mode=defense_confirming — pytest fail means the "
             "defense did NOT hold"],
        )

    # UNCLASSIFIED — return inconclusive with a diagnostic hint.
    hint = attestation_diagnostic_hint(tc)
    evidence = ["UNCLASSIFIED — Resolver did not tag binding and Generator did not emit attestation_mode"]
    if hint:
        evidence.append(hint)
    return ("inconclusive", evidence)
