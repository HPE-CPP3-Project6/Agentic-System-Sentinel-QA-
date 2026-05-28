"""Bootstrap the Sentinel test identity against a freshly deployed target.

In cloud runs, every container starts with a clean target (SQLite is recreated
on `Base.metadata.create_all` at app startup). We need:
    1. Wait for the target to answer /health  (it just booted in a sidecar).
    2. Ensure a known test user exists      (POST /register, treat 409 as OK).
    3. Exchange credentials for a JWT       (POST /login — OAuth2 form-grant).
    4. Emit SENTINEL_TEST_BEARER_TOKEN so the pipeline's pytest_runner can use it.

Output contract (consumed by entrypoint.sh):
    On success, the LAST stdout line is exactly:
        SENTINEL_TEST_BEARER_TOKEN=<jwt>
    The entrypoint extracts that line with `tail -1` and exports it.
    All other diagnostics go to stderr so the contract stays clean.

Env vars (with sane defaults — entrypoint can override):
    SENTINEL_BASE_URL              (required)  e.g. http://127.0.0.1:8000
    SENTINEL_TEST_USER_EMAIL       default: sentinel-qa@example.com
    SENTINEL_TEST_USER_PASSWORD    default: Sentinel-QA-Bootstrap-2026!
    SENTINEL_HEALTH_TIMEOUT_SEC    default: 60
    SENTINEL_HEALTH_PATH           default: /health

Exit codes:
    0  success — JWT printed on last stdout line
    2  target /health never returned 200 within timeout
    3  registration failed with a non-409 error
    4  login failed (after successful registration / 409)
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from typing import Optional

import httpx

# --------------------------------------------------------------------------- #
# Configuration                                                                #
# --------------------------------------------------------------------------- #


def _env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    val = os.environ.get(name, "").strip() or (default or "")
    if required and not val:
        print(f"[setup_target] missing required env var: {name}", file=sys.stderr)
        sys.exit(2)
    return val


BASE_URL = _env("SENTINEL_BASE_URL", required=True).rstrip("/")
# H7: randomize per-run email so concurrent Sentinel runs (Phase 2 per-PR
# isolation) don't share the same identity against a single target. The
# explicit override path still works for reproducible local debugging.
_DEFAULT_EMAIL = f"sentinel-qa-{uuid.uuid4().hex[:8]}@example.com"
EMAIL = _env("SENTINEL_TEST_USER_EMAIL", _DEFAULT_EMAIL)
PASSWORD = _env("SENTINEL_TEST_USER_PASSWORD", "Sentinel-QA-Bootstrap-2026!")
HEALTH_TIMEOUT_SEC = int(_env("SENTINEL_HEALTH_TIMEOUT_SEC", "60"))
HEALTH_PATH = _env("SENTINEL_HEALTH_PATH", "/health")


# --------------------------------------------------------------------------- #
# Steps                                                                        #
# --------------------------------------------------------------------------- #


def wait_for_health(client: httpx.Client) -> None:
    """Poll `/health` every second until 200 or timeout. Targets just-booted apps."""
    deadline = time.monotonic() + HEALTH_TIMEOUT_SEC
    last_err: Optional[str] = None
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            r = client.get(HEALTH_PATH, timeout=5.0)
            if r.status_code == 200:
                print(
                    f"[setup_target] target healthy after {attempt} probes "
                    f"({HEALTH_PATH} → 200)",
                    file=sys.stderr,
                )
                return
            last_err = f"status={r.status_code} body={r.text[:200]!r}"
        except httpx.HTTPError as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)

    print(
        f"[setup_target] target {BASE_URL}{HEALTH_PATH} never returned 200 "
        f"within {HEALTH_TIMEOUT_SEC}s. Last: {last_err}",
        file=sys.stderr,
    )
    sys.exit(2)


def ensure_user(client: httpx.Client) -> None:
    """POST /register. 201 = created, 409 = already exists (both fine)."""
    r = client.post(
        "/register",
        json={"email": EMAIL, "password": PASSWORD},
        timeout=10.0,
    )
    if r.status_code == 201:
        print(f"[setup_target] registered test user {EMAIL}", file=sys.stderr)
        return
    if r.status_code == 409:
        print(
            f"[setup_target] test user {EMAIL} already exists (409) — reusing",
            file=sys.stderr,
        )
        return
    print(
        f"[setup_target] /register unexpected status {r.status_code}: "
        f"{r.text[:300]!r}",
        file=sys.stderr,
    )
    sys.exit(3)


def login_and_get_jwt(client: httpx.Client) -> str:
    """POST /login as OAuth2 password-grant (form-encoded). Returns access_token."""
    # FastAPI's OAuth2PasswordRequestForm takes `username` (carrying the email)
    # and `password` as application/x-www-form-urlencoded fields — NOT JSON.
    r = client.post(
        "/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10.0,
    )
    if r.status_code != 200:
        print(
            f"[setup_target] /login failed status={r.status_code} "
            f"body={r.text[:300]!r}",
            file=sys.stderr,
        )
        sys.exit(4)

    try:
        token = r.json()["access_token"]
    except (ValueError, KeyError) as exc:
        print(
            f"[setup_target] /login response missing access_token: {exc} "
            f"body={r.text[:300]!r}",
            file=sys.stderr,
        )
        sys.exit(4)

    print(f"[setup_target] obtained JWT (len={len(token)})", file=sys.stderr)
    return token


# --------------------------------------------------------------------------- #
# Entry                                                                        #
# --------------------------------------------------------------------------- #


def main() -> int:
    print(
        f"[setup_target] bootstrapping against {BASE_URL} "
        f"(user={EMAIL}, health_timeout={HEALTH_TIMEOUT_SEC}s)",
        file=sys.stderr,
    )
    with httpx.Client(base_url=BASE_URL, follow_redirects=True) as client:
        wait_for_health(client)
        ensure_user(client)
        token = login_and_get_jwt(client)

    # CONTRACT: last stdout line is exactly the export-ready KEY=VALUE pair.
    # entrypoint.sh consumes via `eval $(python -m cloud.setup_target | tail -1)`.
    print(f"SENTINEL_TEST_BEARER_TOKEN={token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
