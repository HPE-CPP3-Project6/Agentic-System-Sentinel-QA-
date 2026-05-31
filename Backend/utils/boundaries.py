"""OWASP resilience / vulnerability signatures for Security+Compiler."""

from __future__ import annotations

# ============================================================================
# RESILIENCE SIGNATURES (What "Safe" Looks Like)
# ============================================================================

RESILIENCE_SIGNATURES = {
    "A03_INJECTION": {
        # 400 = app-level rejection; 422 = Pydantic field validation (EmailStr,
        # constr, etc.) catches malformed input; 401 = the attack reached
        # an auth route (e.g. /login) and the credentials simply didn't match
        # because the payload was treated as a literal string — i.e. the
        # injection was successfully NEUTRALIZED. Without 401 in this list,
        # every SQLi/XSS/Command/NoSQL attempt against /login marks the app
        # as "vulnerable" even when it correctly returned a generic 401.
        # (Observed: exec-demo 2026-05-28 16:37 — 26 false-positive
        # vulnerabilities all from this gap.)
        "http_status": [400, 401, 422],
        "forbidden_keywords": ["SQL", "syntax error", "database error", "ORA-", "SQLSTATE"],
        "expected_behavior": "Input treated as literal string or rejected as invalid",
        "safe_response_example": '{"error": "Invalid input", "code": "VALIDATION_ERROR"}',
    },
    "A01_ACCESS_CONTROL": {
        "http_status": [401, 403, 404],  # 401 added for unauthenticated cross-tenant attempts
        "forbidden_keywords": [],
        "expected_behavior": "Request denied or resource not revealed",
        "safe_response_example": '{"error": "Forbidden", "code": "UNAUTHORIZED"}',
    },
    "A07_AUTH_FAILURE": {
        "http_status": [401, 403, 429],  # 429 added for rate-limited brute-force defence
        "forbidden_keywords": ["user exists", "user not found", "password incorrect", "account locked"],
        "expected_behavior": "Generic rejection without revealing account state",
        "safe_response_example": '{"error": "Invalid credentials"}',
    },
    "A04_INSECURE_DESIGN": {
        # 401 added: an oversized credential payload against /login is
        # correctly neutralized by the auth lookup failing — the test
        # should NOT report this as "vulnerable" just because the status
        # isn't a 400/413. 413 added because explicit Content-Length
        # rejection is also a valid resilience outcome.
        "http_status": [200, 400, 401, 413],
        "forbidden_keywords": ["stack trace", "debug", "internal error"],
        "expected_behavior": "No sensitive system information leaked",
        "safe_response_example": '{"error": "An error occurred. Please try again."}',
    },
    # Used when Critic maps A02/A05/A08/A10; previously fell through to empty → 200-only tests.
    "A02_CRYPTO_FAILURE": {
        "http_status": [400, 403, 422],
        "forbidden_keywords": [],
        "expected_behavior": "Sensitive transport or crypto policy enforced; no secret echoed",
        "safe_response_example": '{"error": "Invalid request"}',
    },
    "A05_SECURITY_MISCONFIGURATION": {
        "http_status": [400, 403, 422],
        "forbidden_keywords": ["evil.example", "attacker"],
        "expected_behavior": "Host / config injection does not change routing or trusted host",
        "safe_response_example": '{"error": "Bad request"}',
    },
    "A08_INTEGRITY_FAILURE": {
        "http_status": [400, 422],
        "forbidden_keywords": ["__proto__", "constructor", "prototype"],
        "expected_behavior": "Deserialisation or merge rejects prototype pollution payloads",
        "safe_response_example": '{"error": "Invalid input"}',
    },
    "A10_SSRF": {
        "http_status": [400, 403, 422],
        "forbidden_keywords": ["169.254.169.254", "metadata", "instance-id"],
        "expected_behavior": "Outbound or URL validation blocks metadata / internal targets",
        "safe_response_example": '{"error": "URL not allowed"}',
    },
}

# ============================================================================
# VULNERABILITY SIGNATURES (What "Exploited" Looks Like)
# ============================================================================

VULNERABILITY_SIGNATURES = {
    "A03_INJECTION": {
        "http_status": [200],  # Success with leaked data
        "expected_keywords": ["SQL", "syntax error", "stack trace"],
        "expected_behavior": "Database error or data leaked to attacker",
        "vulnerable_response_example": '{"error": "SQL syntax error: unexpected token", "query": "SELECT * FROM users WHERE id = \'..."}',
    },
    "A01_ACCESS_CONTROL": {
        "http_status": [200],  # Success when it shouldn't be
        "expected_keywords": ["data", "results"],
        "expected_behavior": "Unauthorized data returned to attacker",
        "vulnerable_response_example": '{"user_id": "other_user", "email": "victim@example.com", "ssn": "123-45-6789"}',
    },
    "A07_AUTH_FAILURE": {
        "http_status": [200],  # Login succeeded when it shouldn't
        "expected_keywords": ["token", "session", "authenticated"],
        "expected_behavior": "Authentication bypass; attacker gains access",
        "vulnerable_response_example": '{"status": "authenticated", "token": "...", "user": "admin"}',
    },
    "A04_INSECURE_DESIGN": {
        "http_status": [200, 500],
        "expected_keywords": ["stack trace", "line 123", "file: config.php", "API key"],
        "expected_behavior": "Sensitive system information exposed",
        "vulnerable_response_example": '{"error": "Connection failed at /app/config.php:45 — DB_PASSWORD=..."}',
    },
    "A02_CRYPTO_FAILURE": {
        "http_status": [200],
        "expected_keywords": ["http://internal", "password=", "token="],
        "expected_behavior": "Cleartext or internal URL accepted when it should be refused",
        "vulnerable_response_example": '{"token": "secret", "url": "http://internal-service/"}',
    },
    "A05_SECURITY_MISCONFIGURATION": {
        "http_status": [200, 302],
        "expected_keywords": ["evil.example", "Location: http://evil"],
        "expected_behavior": "Host header or misconfig allows attacker-controlled redirect/host",
        "vulnerable_response_example": '{"redirect": "http://evil.example/"}',
    },
    "A08_INTEGRITY_FAILURE": {
        "http_status": [200],
        "expected_keywords": ["isAdmin", "__proto__", "true"],
        "expected_behavior": "Prototype pollution alters object behaviour or auth flags",
        "vulnerable_response_example": '{"isAdmin": true, "role": "admin"}',
    },
    "A10_SSRF": {
        "http_status": [200],
        "expected_keywords": ["ami-id", "instance-id", "169.254"],
        "expected_behavior": "Server fetched cloud metadata or internal URL and leaked it",
        "vulnerable_response_example": '{"body": "ami-0123456789abcdef0"}',
    },
}
