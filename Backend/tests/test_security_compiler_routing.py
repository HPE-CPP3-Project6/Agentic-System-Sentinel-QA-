"""Golden tests for security_compiler._method_path_from_action (the
four-tier METHOD/path inference chain).

The demo run exec-demo-login-post_code-20260528_154225 had only 6%
executable tests because the Generator's `action` field is natural-language
prose, not the `METHOD /path` shape the original regex required. These tests
pin the new four-tier fallback so that ~80%+ of Generator output now yields
runnable pytest functions.

Order of fallback (first match wins):
  1. METHOD-path regex on `action`
  2. METHOD-path regex on `title`
  3. Bare path in action+title, default POST
  4. Heuristic from input_data shape + title/action keywords

Run from Backend/:
    pytest tests/test_security_compiler_routing.py -v
"""

from __future__ import annotations

import pytest

from agents.security_compiler import _method_path_from_action


# --------------------------------------------------------------------------- #
# Tier 1 — explicit METHOD /path in action (the "correct" Generator output)   #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("action,expected_method,expected_path", [
    ("POST /login with valid credentials",          "POST",   "/login"),
    ("GET /tasks/123 as authenticated user",        "GET",    "/tasks/123"),
    ("DELETE /tasks/42 by a non-owner",             "DELETE", "/tasks/42"),
    ("PATCH /tasks/7 with SQL injection in body",   "PATCH",  "/tasks/7"),
    ("post /register valid credentials",            "POST",   "/register"),  # lowercase
    ("Send POST request to /login with bad email",  "POST",   "/login"),     # method not at start
])
def test_tier1_extracts_method_and_path_from_action(action, expected_method, expected_path):
    meth, path, skip = _method_path_from_action(action)
    assert meth == expected_method
    assert path == expected_path
    assert skip is None


def test_tier1_rejects_path_with_placeholders():
    """{task_id} style placeholders can't be served by the runtime template —
    they need to be inline literals. Skip with a clear reason rather than
    emit a malformed request URL."""
    meth, path, skip = _method_path_from_action("GET /tasks/{task_id} as owner")
    # Falls through tier 1; tiers 2/3 also reject placeholders → ultimately skipped
    # (or tier 4 if input_data hints; here we pass no kwargs so it skips).
    assert meth is None
    assert path is None
    assert skip is not None


# --------------------------------------------------------------------------- #
# Tier 2 — METHOD /path lives in the title instead                            #
# --------------------------------------------------------------------------- #


def test_tier2_falls_back_to_title_when_action_is_prose():
    """The demo-artifact pattern: action is a natural-language verb phrase but
    the title happens to carry the route. Tier 2 should rescue it."""
    meth, path, skip = _method_path_from_action(
        action="Attempt to log in with malformed email",
        title="POST /login with bad email returns 422",
    )
    assert meth == "POST"
    assert path == "/login"
    assert skip is None


# --------------------------------------------------------------------------- #
# Tier 3 — bare path mentioned, no explicit method → default POST             #
# --------------------------------------------------------------------------- #


def test_tier3_bare_path_default_method_is_post():
    """`/login` appears but no GET/POST/etc. nearby — assume POST. Conservative
    because /login is overwhelmingly a POST endpoint."""
    meth, path, skip = _method_path_from_action(
        action="hit /login with very long password",
        title="extreme-length password",
    )
    assert meth == "POST"
    assert path == "/login"
    assert skip is None


# --------------------------------------------------------------------------- #
# Tier 4 — input_data shape + title/action keywords (the rescue tier)         #
# --------------------------------------------------------------------------- #


def test_tier4_email_password_with_register_keyword_routes_to_register():
    """The demo-artifact pattern that was being SKIPPED: action="Register a
    user with a 1000-char password", input_data={email, password}, no path
    anywhere. Tier 4 sees email+password keys + 'register' keyword → /register.
    """
    meth, path, skip = _method_path_from_action(
        action="Register a user with a 1000-char password",
        title="boundary length test",
        input_data={"email": "test@example.com", "password": "x" * 1000},
    )
    assert meth == "POST"
    assert path == "/register"
    assert skip is None


def test_tier4_email_password_without_register_keyword_defaults_to_login():
    """Same shape but the verb is 'log in' → /login. Login is more common
    than register as a test target so this is the safer default."""
    meth, path, skip = _method_path_from_action(
        action="Attempt to log in with bad credentials",
        title="bad creds rejected",
        input_data={"email": "test@example.com", "password": "wrong"},
    )
    assert meth == "POST"
    assert path == "/login"
    assert skip is None


def test_tier4_username_password_form_grant_routes_to_login():
    """OAuth2 password-grant uses `username` (carrying email) + `password` —
    must route to /login, NOT /register."""
    meth, path, skip = _method_path_from_action(
        action="OAuth2 password grant test",
        title="login form",
        input_data={"username": "test@example.com", "password": "x"},
    )
    assert meth == "POST"
    assert path == "/login"
    assert skip is None


def test_tier4_title_keyword_routes_to_known_endpoint():
    """Action and input_data are useless — but title contains 'tasks'.
    Heuristic routes table maps that to GET /tasks/."""
    meth, path, skip = _method_path_from_action(
        action="anonymous probe",
        title="enumerate other users' tasks",
        input_data={},
    )
    assert meth == "GET"
    assert path == "/tasks/"
    assert skip is None


# --------------------------------------------------------------------------- #
# All tiers exhausted — informative skip                                       #
# --------------------------------------------------------------------------- #


def test_all_tiers_exhausted_returns_informative_skip_reason():
    """When nothing in action/title/input_data hints at a route, the skip
    reason MUST tell the dev what we tried (so triage isn't guesswork)."""
    meth, path, skip = _method_path_from_action(
        action="some abstract thing",
        title="vague description",
        input_data={"random_field": "value"},
    )
    assert meth is None
    assert path is None
    assert skip is not None
    # Must name the inputs the inference examined
    assert "action=" in skip
    assert "title=" in skip
    assert "input_data" in skip


# --------------------------------------------------------------------------- #
# Backward-compat with single-arg legacy callers                              #
# --------------------------------------------------------------------------- #


def test_legacy_single_arg_call_still_works():
    """If anyone still calls `_method_path_from_action(tc.action)` without
    kwargs, tier 1 + tier 3 still fire. Tier 2 + 4 don't (no title /
    input_data) but the function doesn't crash."""
    meth, path, skip = _method_path_from_action("POST /login with bad creds")
    assert meth == "POST"
    assert path == "/login"
    assert skip is None

    # Single-arg call with prose-only action → must skip cleanly (no crash)
    meth, path, skip = _method_path_from_action("Attempt to log in")
    assert meth is None
    assert path is None
    assert skip is not None
