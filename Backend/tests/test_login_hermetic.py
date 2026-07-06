"""ensure_absent_login_identity — make 'non-existent user' logins hermetic.

Regression for TC-REQ-003a-03: a negative login (expects 401) with a literal
benign identity accidentally SUCCEEDED because a prior run had registered that
exact email/password in the never-reset target DB. The helper rewrites benign
401-login identities to a fresh, never-registered value so the rejection is
reproducible across runs, while leaving attack-payload probes untouched.
"""

from __future__ import annotations

from utils.pytest_harness import (
    ensure_absent_login_identity,
    query_param_test_unexercised,
)


def _call(payload, expected, adv=True, path="/login"):
    return ensure_absent_login_identity(
        payload, path=path, is_adversarial=adv, expected_status_code=expected
    )


def test_benign_401_login_is_rewritten_to_fresh_identity():
    p = {"username": "nonexistent@example.com", "password": "AnyPassword123"}
    out = _call(p, 401)
    assert out["username"] != "nonexistent@example.com"
    assert out["username"].startswith("sentinel-absent-")
    assert out["password"] == "AnyPassword123"  # password preserved
    assert p["username"] == "nonexistent@example.com"  # input not mutated


def test_attack_payload_login_is_left_untouched():
    p = {"username": "' OR 1=1--", "password": "x"}
    assert _call(p, 401) == p  # the payload IS the probe


def test_happy_path_login_untouched():
    p = {"username": "user@example.com", "password": "Correct1"}
    assert _call(p, 200, adv=False) is p


def test_422_login_untouched():
    p = {"username": "user@example.com", "password": "x"}
    assert _call(p, 422) is p


def test_non_login_path_untouched():
    p = {"email": "user@example.com", "password": "x"}
    assert _call(p, 401, path="/register") is p


def test_email_field_variant_is_rewritten():
    # No username key, but an email key present.
    p = {"email": "nonexistent@example.com", "password": "AnyPassword123"}
    out = _call(p, 401)
    assert out["email"].startswith("sentinel-absent-")


# ─── query_param_test_unexercised — the 011a false-red guard ──────────────


def test_get_validation_error_with_empty_params_is_skipped():
    assert query_param_test_unexercised("GET", {}, 422) is True
    assert query_param_test_unexercised("GET", {}, 400) is True


def test_get_with_encoded_param_is_not_skipped():
    assert query_param_test_unexercised("GET", {"limit": 101}, 422) is False


def test_get_success_expectation_is_not_skipped():
    # A GET expecting 200/401/404 is untouched even with empty params.
    assert query_param_test_unexercised("GET", {}, 200) is False
    assert query_param_test_unexercised("GET", {}, 401) is False
    assert query_param_test_unexercised("GET", {}, 404) is False


def test_non_get_methods_are_not_skipped():
    # POST /register with empty body expecting 422 is a body-validation test,
    # not a query-param probe — must NOT be skipped by this guard.
    assert query_param_test_unexercised("POST", {}, 422) is False
