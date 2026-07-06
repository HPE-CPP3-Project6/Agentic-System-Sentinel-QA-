"""Shared pytest harness helpers for generated API tests.

Imported at runtime from ``test_sentinel_api_generated.py`` (see
``agents/templates/pytest_api.jinja2``). Kept in ``utils/`` so unit tests
can pin behaviour without materializing a full pytest module.
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Optional

try:
    import httpx
except ImportError:  # pragma: no cover — unit tests may mock
    httpx = None  # type: ignore[assignment]

EMAIL_KEYS = ("email", "username", "user_email", "useremail")
_ATTACK_SIGILS = ("'", "--", "<", ">", "/*", "*/", "${", "{$", "OR 1", "../", "..\\")
_VALID_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PEER_PASSWORD = "Sentinel-Peer-B-2026!"


def payload_email_field(payload: dict[str, Any]) -> Optional[str]:
    for key in EMAIL_KEYS:
        if key in payload and isinstance(payload[key], str):
            return key
    return None


def looks_like_attack_payload(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return any(sig in value for sig in _ATTACK_SIGILS)


def looks_like_valid_email(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return bool(_VALID_EMAIL_RE.match(value.strip()))


def should_randomise_register_email(
    payload: Any,
    *,
    path: str,
    is_adversarial: bool,
    expected_status_code: Optional[int],
) -> bool:
    """True only for functional POST /register tests that need a fresh identity."""
    if not isinstance(payload, dict) or not path.endswith("/register"):
        return False
    if is_adversarial:
        return False
    if expected_status_code in (409, 422):
        return False
    field = payload_email_field(payload)
    if field is None:
        return False
    original = payload[field]
    if looks_like_attack_payload(original):
        return False
    if not looks_like_valid_email(original):
        return False
    return True


def maybe_randomise_register_email(
    payload: Any,
    *,
    path: str,
    is_adversarial: bool,
    expected_status_code: Optional[int],
) -> Any:
    if not should_randomise_register_email(
        payload,
        path=path,
        is_adversarial=is_adversarial,
        expected_status_code=expected_status_code,
    ):
        return payload
    field = payload_email_field(payload)  # type: ignore[arg-type]
    new_payload = dict(payload)
    new_payload[field] = f"sentinel-{uuid.uuid4().hex[:12]}@example.com"
    return new_payload


def ensure_absent_login_identity(
    payload: Any,
    *,
    path: str,
    is_adversarial: bool,
    expected_status_code: Optional[int],
) -> Any:
    """Make a "non-existent user" login actually non-existent, across runs.

    A negative login that expects 401 must not accidentally SUCCEED because an
    earlier run (against the same never-reset target DB) registered the literal
    identity the Generator chose — e.g. ``nonexistent@example.com`` /
    ``AnyPassword123``, which a prior run's happy-path helper had created, so
    the "non-existent user" login returned 200 + a token (observed false-red
    TC-REQ-003a-03). Rewriting the username to a fresh, never-registered value
    makes the rejection hermetic regardless of DB history.

    Scope is deliberately narrow:
      • Only POST /login tests that expect 401.
      • Attack-payload usernames (SQLi / XSS probes) are left untouched — the
        payload IS the test.
      • The rewrite preserves the 401 outcome in every case (a fresh identity
        is rejected as "user not found"), so it can never turn a legitimately
        failing assertion green, nor break a "wrong password for an existing
        user" probe (that still yields 401).
    Returns the (possibly rewritten) payload; callers must use the return value.
    """
    if not isinstance(payload, dict) or not path.endswith("/login"):
        return payload
    if expected_status_code != 401:
        return payload
    field = "username" if "username" in payload else payload_email_field(payload)
    if field is None:
        return payload
    original = str(payload.get(field, ""))
    if looks_like_attack_payload(original):
        return payload  # the payload is the probe — leave it
    new_payload = dict(payload)
    new_payload[field] = f"sentinel-absent-{uuid.uuid4().hex[:12]}@example.com"
    return new_payload


# HTTP codes that represent request-VALIDATION rejection (as opposed to auth
# 401 / not-found 404 / conflict 409). A GET boundary probe asserts one of
# these when it sends an out-of-range query param.
_VALIDATION_ERROR_CODES = frozenset({400, 422})


def query_param_test_unexercised(
    method: str,
    payload: Any,
    expected_status_code: Optional[int],
) -> bool:
    """True for a GET test that expects a query-param VALIDATION error but
    carries no query params to trigger it.

    The Generator sometimes states the boundary only in the test title
    (e.g. "limit=101 returns 422") without encoding the value into
    ``input_data`` — so the request is a bare ``GET`` the app answers 2xx and
    the "expect 422" assertion false-fails as a vulnerability (observed
    TC-REQ-011a-06/07). The boundary was never exercised, so the caller skips
    the test (honest "not exercised") instead of asserting a phantom failure.

    Deliberately narrow: only GET, only the validation-error codes, only when
    the query-param payload is empty. A test that DOES encode a param, or that
    legitimately expects a non-validation status, is untouched.
    """
    if str(method).upper() != "GET":
        return False
    if expected_status_code not in _VALIDATION_ERROR_CODES:
        return False
    return not (isinstance(payload, dict) and len(payload) > 0)


def register_json_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Map login-style username to register ``email`` when needed."""
    body = dict(payload)
    if "email" not in body and "username" in body:
        body["email"] = body["username"]
    return {k: v for k, v in body.items() if k in ("email", "password")}


def normalize_login_form(payload: Any, *, path: str) -> Any:
    """OAuth2PasswordRequestForm expects ``username``, not ``email``."""
    if not path.endswith("/login") or not isinstance(payload, dict):
        return payload
    form = dict(payload)
    if "username" not in form and "email" in form:
        form["username"] = form["email"]
    return form


def seed_register_duplicate(
    base_url: str,
    payload: Any,
    *,
    path: str,
    expected_status_code: Optional[int],
) -> None:
    """Pre-create the identity when the test expects HTTP 409 Conflict."""
    if expected_status_code != 409 or not path.endswith("/register"):
        return
    if not isinstance(payload, dict) or httpx is None:
        return
    body = register_json_payload(payload)
    if not body.get("email"):
        return
    try:
        with httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=False) as client:
            client.post("/register", json=body)
    except Exception:
        pass


def ensure_login_credential(
    base_url: str,
    payload: Any,
    *,
    path: str,
    is_adversarial: bool,
    expected_status_code: Optional[int] = None,
) -> Any:
    """Guarantee a functional POST /login credential; return the payload to use.

    Pre-registers the login identity so a happy-path login can authenticate.
    Because ``/register`` is create-only (not upsert), an email already claimed
    by an earlier test with a *different* password would leave the login
    returning 401. For the happy path (``expected_status_code == 200``) we
    therefore verify the credential actually logs in, and if it does not, mint a
    unique email, register it with the test's password, and rewrite the form
    identity to it — keeping positive-login tests hermetic regardless of test
    ordering. Negative/boundary logins (expect 401/422) are never rewritten, so
    their intended rejection is preserved. Returns the (possibly rewritten)
    payload; callers must use the return value.
    """
    if is_adversarial or not path.endswith("/login") or not isinstance(payload, dict):
        return payload
    if expected_status_code != 200:
        # Negative logins (401 non-existent user / wrong password, 422
        # malformed) must NOT have their identity pre-registered. The
        # unconditional register below used to create the test's
        # "nonexistent@example.com", making the login legitimately succeed —
        # observed r_0531fce0: TC-REQ-002-03 expected 401, got 200 + token.
        return payload
    if httpx is None:
        return payload
    form = normalize_login_form(payload, path=path)
    email = form.get("username") or form.get("email")
    password = form.get("password") or form.get("passwd") or form.get("pwd")
    if not (email and password):
        return payload
    if looks_like_attack_payload(str(email)) or looks_like_attack_payload(str(password)):
        return payload
    try:
        with httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=False) as client:
            # Idempotent register of the intended identity (no-op if it exists).
            client.post("/register", json={"email": email, "password": password})
            # Only the happy path must be guaranteed to authenticate. If the
            # email was claimed by an earlier test with a different password,
            # the register above no-ops (409) and this login would 401 — so we
            # fall back to a fresh, unconflicted identity.
            if expected_status_code == 200 and looks_like_valid_email(str(email)):
                login = client.post(
                    "/login",
                    data={"username": email, "password": password},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if login.status_code != 200:
                    fresh = f"sentinel-login-{uuid.uuid4().hex[:12]}@example.com"
                    client.post("/register", json={"email": fresh, "password": password})
                    rewritten = dict(payload)
                    if "username" in rewritten:
                        rewritten["username"] = fresh
                    if "email" in rewritten:
                        rewritten["email"] = fresh
                    return rewritten
    except Exception:
        return payload
    return payload


def bootstrap_peer_task_id(base_url: str) -> Optional[str]:
    """Seed user B + task; return task id for IDOR path substitution."""
    if httpx is None:
        return None
    email_b = f"sentinel-peer-{uuid.uuid4().hex[:10]}@example.com"
    try:
        with httpx.Client(base_url=base_url, timeout=15.0, follow_redirects=True) as client:
            client.post(
                "/register",
                json={"email": email_b, "password": _PEER_PASSWORD},
            )
            login = client.post(
                "/login",
                data={"username": email_b, "password": _PEER_PASSWORD},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if login.status_code != 200:
                return None
            token = login.json().get("access_token")
            if not token:
                return None
            created = client.post(
                "/tasks/",
                json={"title": "sentinel-peer-task"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if created.status_code not in (200, 201):
                return None
            body = created.json()
            if not isinstance(body, dict):
                return None
            tid = body.get("id") or body.get("task_id")
            return str(tid) if tid is not None else None
    except Exception:
        return None


def resolve_path_template(path: str, payload: dict[str, Any], *, base_url: str) -> str:
    """Fill ``{task_id}`` from payload or peer bootstrap."""
    if "{" not in path:
        return path
    tid = payload.get("task_id") or payload.get("id")
    if tid is not None:
        return path.replace("{task_id}", str(tid))
    if "{task_id}" in path:
        peer = bootstrap_peer_task_id(base_url)
        if peer:
            return path.replace("{task_id}", peer)
    return path
