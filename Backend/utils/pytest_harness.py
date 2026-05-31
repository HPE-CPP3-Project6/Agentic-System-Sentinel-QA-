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
) -> None:
    """Idempotently register before a functional POST /login."""
    if is_adversarial or not path.endswith("/login") or not isinstance(payload, dict):
        return
    if httpx is None:
        return
    form = normalize_login_form(payload, path=path)
    email = form.get("username") or form.get("email")
    password = form.get("password") or form.get("passwd") or form.get("pwd")
    if not (email and password):
        return
    if looks_like_attack_payload(str(email)) or looks_like_attack_payload(str(password)):
        return
    body = {"email": email, "password": password}
    try:
        with httpx.Client(base_url=base_url, timeout=10.0, follow_redirects=False) as client:
            client.post("/register", json=body)
    except Exception:
        pass


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
