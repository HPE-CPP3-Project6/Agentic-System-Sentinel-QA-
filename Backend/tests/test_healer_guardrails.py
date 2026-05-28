"""Golden tests for the Healer safety guardrails (NEW-5) and prior-patch
awareness (H8). These pin the patterns the demo artifact exposed:

  exec-demo-login-post_code-20260528_055917.json showed the Healer proposing:
    1. Hardcoded test credentials inside auth.py (backdoor)
    2. Custom RequestValidationError handlers that remap 422 -> 400
       (framework override to satisfy wrong test expectations)
    3. The SAME patch in cycle 1 and cycle 2 with no awareness

If any of these patterns slip back in unflagged, these tests fail loudly.

Run from Backend/:
    pytest tests/test_healer_guardrails.py -v
"""

from __future__ import annotations

from typing import List

import pytest

from agents.executor import (
    _dedup_suggested_patches,
    _format_prior_patches,
    _validate_patch_safety,
)
from state import Patch


# --------------------------------------------------------------------------- #
# NEW-5 — _validate_patch_safety must flag every backdoor pattern             #
# --------------------------------------------------------------------------- #


def test_clean_patch_passes_validation():
    """A reasonable security fix (parameterized query) must NOT trigger any
    warning. Negative control for the detector — false positives erode trust."""
    safe = (
        "def get_user(db, email: str):\n"
        "    return db.execute(\n"
        "        text('SELECT * FROM users WHERE email = :email'),\n"
        "        {'email': email},\n"
        "    ).fetchone()\n"
    )
    assert _validate_patch_safety(safe, "auth.py") is None


def test_empty_fix_is_not_flagged():
    """Empty suggested_fix is the Healer correctly opting out (R2/R3) — must
    NOT be flagged as unsafe. The bug_explanation carries the rationale."""
    assert _validate_patch_safety("", "auth.py") is None
    assert _validate_patch_safety("   \n  ", "auth.py") is None


def test_hardcoded_email_in_auth_is_flagged_unsafe():
    """The exact demo-artifact pattern: `if email == "test@example.com"` inside
    authenticate_user. Must produce an UNSAFE PATCH warning, ESCALATED because
    the target_file is an auth file."""
    backdoor = (
        'def authenticate_user(db, email, password):\n'
        '    if email == "test@example.com" and password == "Password123":\n'
        '        return _seed_test_user(db, email, password)\n'
        '    # original auth ...\n'
    )
    warning = _validate_patch_safety(backdoor, "auth.py")
    assert warning is not None
    assert "UNSAFE PATCH" in warning
    assert "auth/config target" in warning
    assert "DO NOT AUTO-MERGE" in warning
    assert "hardcoded_email_compare" in warning


def test_silent_password_overwrite_is_flagged():
    """The other half of the TC-REQ-004-01 backdoor — mutating an existing
    hashed_password silently to make the test pass."""
    overwrite = (
        "user_for_test.hashed_password = hash_password(password)\n"
        "db.commit()\n"
    )
    warning = _validate_patch_safety(overwrite, "auth.py")
    assert warning is not None
    assert "silent_password_overwrite" in warning


def test_pydantic_422_to_400_remap_is_flagged():
    """The custom RequestValidationError → HTTP_400_BAD_REQUEST pattern from
    SEC-A03-TC-REQ-003-01-2/3/4 in the demo artifact. This is the framework-
    override anti-pattern that NEW-4 + Generator prompt fix targets at the
    source — the validator catches it at the sink too."""
    bad_override = (
        "from fastapi.exceptions import RequestValidationError\n"
        "@router.exception_handler(RequestValidationError)\n"
        "async def validation_exception_handler(request, exc):\n"
        "    return JSONResponse(\n"
        "        status_code=status.HTTP_400_BAD_REQUEST,\n"
        "        content={'detail': exc.errors()},\n"
        "    )\n"
    )
    warning = _validate_patch_safety(bad_override, "routers/auth_router.py")
    assert warning is not None
    assert "pydantic_422_to_400_override" in warning


def test_hardcoded_token_or_key_is_flagged():
    """Bearer tokens or API keys hardcoded into a patch — explicit secret leak."""
    leak = (
        "headers = {'Authorization': 'Bearer eyJhbGciOiJIUzI1NiJ9.dGVzdA.x' * 5}\n"
        "SECRET_KEY = 'super_secret_dev_key_abc123def456'\n"
    )
    warning = _validate_patch_safety(leak, "settings.py")
    assert warning is not None
    assert "UNSAFE PATCH (auth/config target)" in warning


def test_warning_on_non_sensitive_file_is_still_emitted_but_not_escalated():
    """If a backdoor pattern lands in a non-auth file (e.g., a route file),
    it's still flagged — just without the auth-escalation phrasing."""
    backdoor = (
        'if email == "leaktest@example.com":\n'
        '    return secret_data\n'
    )
    warning = _validate_patch_safety(backdoor, "routers/task_router.py")
    assert warning is not None
    assert "UNSAFE PATCH" in warning
    # Non-sensitive path → no auth-escalation phrase
    assert "auth/config target" not in warning


# --------------------------------------------------------------------------- #
# H8 — Healer prior-patch awareness                                            #
# --------------------------------------------------------------------------- #


def _patch(test_id: str, heal_attempt: int, fix: str = "x") -> Patch:
    return Patch(
        target_file="auth.py",
        bug_explanation="x",
        suggested_fix=fix,
        related_test_ids=[test_id],
        owasp_category="A03:2021",
        heal_attempt=heal_attempt,
    )


def test_format_prior_patches_empty_returns_helpful_string():
    """When no prior cycles exist, the prompt block must NOT be blank — that
    confuses the LLM into thinking it's missing context."""
    rendered = _format_prior_patches([], "TC-REQ-004-01")
    assert "first heal attempt" in rendered


def test_format_prior_patches_only_includes_matching_test_id():
    """Patches for other tests must NOT leak into this test's context — would
    confuse the Healer and waste prompt tokens."""
    patches = [
        _patch("TC-REQ-001-01", heal_attempt=1, fix="patch for req-1"),
        _patch("TC-REQ-004-01", heal_attempt=1, fix="patch for req-4"),
    ]
    rendered = _format_prior_patches(patches, "TC-REQ-004-01")
    assert "patch for req-4" in rendered
    assert "patch for req-1" not in rendered


def test_format_prior_patches_truncates_long_output():
    """Prevent the prior-patches block from monopolising the prompt token budget."""
    huge_fix = "x" * 10_000
    patches = [_patch("TC-REQ-001-01", heal_attempt=1, fix=huge_fix)]
    rendered = _format_prior_patches(patches, "TC-REQ-001-01", max_chars=500)
    assert len(rendered) <= 600  # 500 budget + "... (truncated)" tail
    assert "truncated" in rendered


# --------------------------------------------------------------------------- #
# NEW-3 + H3 — Patch dedup across heal cycles                                  #
# --------------------------------------------------------------------------- #


def test_dedup_replaces_prior_cycle_patch_for_same_test():
    """The demo-artifact regression: 16 cycle-2 patches accumulated to 31 in
    suggested_patches because of `state.suggested_patches.extend(new_patches)`.
    The dedup must REPLACE — not append — when the (test, owasp) identity matches.
    """
    cycle1 = [_patch("TC-1", heal_attempt=1, fix="v1")]
    cycle2_same = [_patch("TC-1", heal_attempt=2, fix="v2")]

    deduped = _dedup_suggested_patches(cycle1, cycle2_same)

    assert len(deduped) == 1, "same (test, owasp) must collapse, not accumulate"
    assert deduped[0].heal_attempt == 2, "latest cycle wins"
    assert deduped[0].suggested_fix == "v2"


def test_dedup_keeps_distinct_tests_and_owasp_buckets():
    """Two patches for the same test under DIFFERENT owasp categories represent
    distinct hypotheses about the failure — keep both, don't collapse."""
    existing = [
        _patch("TC-1", heal_attempt=1, fix="sql-fix"),
    ]
    existing[0].owasp_category = "A03:2021"

    new = [
        _patch("TC-1", heal_attempt=2, fix="authn-fix"),
        _patch("TC-2", heal_attempt=2, fix="other-test"),
    ]
    new[0].owasp_category = "A07:2021"  # different bucket → distinct hypothesis
    new[1].owasp_category = "A03:2021"

    deduped = _dedup_suggested_patches(existing, new)
    assert len(deduped) == 3
