"""Shared adversarial attestation semantics — single source of truth.

ARCHITECTURE (Stage 2 — needles removed)
========================================

``attestation_mode`` is a property of the BINDING, not the test. The
Resolver classifies each requirement's binding as ``missing_control``
(control absent in code, gap-attestation needed) or ``defense_confirming``
(defense present, verify it holds). The Generator inherits the binding's
mode onto each adversarial TestCase. The Classifier (pytest_runner) reads
the stamped value and decides the verdict.

There are NO title / expected_result needles in the verdict path. The
legacy ``test_signals_missing_control`` and ``attestation_diagnostic_hint``
helpers were retired in Stage 2 after the Stage-1 cascade proved stable.
If a verdict is wrong, the fix is at one of these layers — never here:

  1. Resolver tagged the binding wrong → fix the Resolver prompt /
     ``_promote_missing_control_binding`` heuristic.
  2. Generator dropped the stamp → tighten the OUTPUT SCHEMA constraint
     on attestation_mode in generator.py.
  3. The test was authored in the wrong style → the Generator emitted
     a style-1 design for what should have been style-2 (or vice versa);
     fix at the prompt level.

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
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from state import SurfaceBinding, TestCase


# ─── Helpers ──────────────────────────────────────────────────────────────


def _action_targets_register(tc: TestCase) -> bool:
    """Used only to gate the /register-specific style-2 rule (status 400 as
    the anti-enumeration sentinel). This is a structural route check, not a
    title needle — its scope is bounded to ``_is_style_2_design``.
    """
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


_UNCLASSIFIED_EVIDENCE = (
    "UNCLASSIFIED — Resolver did not tag binding and Generator did not "
    "emit attestation_mode; fix at the Resolver or Generator layer"
)


def adversarial_verdict_on_pass(
    tc: TestCase,
    binding: Optional[SurfaceBinding] = None,
) -> Tuple[str, List[str]]:
    """Return (verdict, evidence) when pytest reports the adversarial test
    as ``passed``. Decision is the cascade — no string heuristics."""
    mode = infer_attestation_mode(tc, binding)

    if mode == "missing_control":
        if _is_style_2_design(tc):
            return (
                "resilient",
                [
                    "attestation_mode=missing_control (style-2) — pass means "
                    f"expected enforcement status {tc.expected_status_code} "
                    "fired; control is unexpectedly present"
                ],
            )
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

    return ("inconclusive", [_UNCLASSIFIED_EVIDENCE])


def adversarial_verdict_on_fail(
    tc: TestCase,
    detail: str,
    binding: Optional[SurfaceBinding] = None,
) -> Tuple[str, List[str]]:
    """Return (verdict, evidence) when pytest reports the adversarial test
    as ``failed``. Decision is the cascade — no string heuristics."""
    mode = infer_attestation_mode(tc, binding)

    if mode == "missing_control":
        if _is_style_2_design(tc):
            actual = _actual_status_from_detail(detail)
            hint = (
                "anti-enumeration (generic 400) missing"
                if tc.expected_status_code == 400 and _action_targets_register(tc)
                else "rate limit / lockout missing"
            )
            return (
                "vulnerable",
                [
                    f"attestation_mode=missing_control (style-2) — expected "
                    f"enforcement status {tc.expected_status_code}, "
                    f"got {actual if actual is not None else '?'} ({hint})"
                ],
            )
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

    return ("inconclusive", [_UNCLASSIFIED_EVIDENCE])
