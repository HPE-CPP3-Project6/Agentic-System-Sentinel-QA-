"""Attack & Boundary Profile Library for Test Case Generation.

Provides standardized boundary conditions, attack vectors, and technical
profiles for the Generator and Security+Compiler agents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class BoundaryProfile:
    """A boundary test profile: exact values for testing limits."""

    name: str
    description: str
    test_values: List[Any]


# ============================================================================
# STRING BOUNDARIES
# ============================================================================

STRING_BOUNDARIES = {
    "empty": BoundaryProfile(
        name="Empty String",
        description="Test empty/null input",
        test_values=["", None],
    ),
    "whitespace": BoundaryProfile(
        name="Whitespace Only",
        description="Test strings with only whitespace",
        test_values=[" ", "\n", "\t", "   \n   "],
    ),
    "max_valid": BoundaryProfile(
        name="Maximum Valid Length",
        description="String at exactly the declared limit",
        test_values=None,  # Computed from AC (e.g., 255 chars)
    ),
    "max_overflow": BoundaryProfile(
        name="Maximum + 1 (Overflow)",
        description="String exceeding declared limit by 1 char",
        test_values=None,  # Computed from AC (e.g., 256 chars if limit is 255)
    ),
    "max_extreme": BoundaryProfile(
        name="Extreme Overflow",
        description="String 1000+ chars to stress-test buffer handling",
        test_values=None,  # Computed dynamically
    ),
}

# ============================================================================
# NUMERIC BOUNDARIES
# ============================================================================

NUMERIC_BOUNDARIES = {
    "zero": BoundaryProfile(
        name="Zero",
        description="Test zero value",
        test_values=[0],
    ),
    "negative": BoundaryProfile(
        name="Negative",
        description="Test negative values",
        test_values=[-1, -100, -999999],
    ),
    "max_int32": BoundaryProfile(
        name="Max Int32",
        description="Test integer overflow (2^31 - 1)",
        test_values=[2147483647],
    ),
    "overflow_int32": BoundaryProfile(
        name="Int32 Overflow",
        description="Test value exceeding 32-bit signed integer",
        test_values=[2147483648],
    ),
    "max_int64": BoundaryProfile(
        name="Max Int64",
        description="Test 64-bit integer boundary",
        test_values=[9223372036854775807],
    ),
}

# ============================================================================
# SQL INJECTION PATTERNS (A03)
# ============================================================================

SQL_INJECTION_PATTERNS = {
    "basic_or": BoundaryProfile(
        name="Basic OR Injection",
        description="Classic ' OR 1=1 -- pattern",
        test_values=["' OR 1=1 --", "' OR '1'='1"],
    ),
    "union_select": BoundaryProfile(
        name="UNION SELECT Injection",
        description="Data exfiltration via UNION",
        test_values=[
            "' UNION SELECT null, username, password FROM users --",
            "1' UNION ALL SELECT NULL, NULL, NULL --",
        ],
    ),
    "stacked_queries": BoundaryProfile(
        name="Stacked Query Injection",
        description="Execute multiple statements",
        test_values=[
            "'; DROP TABLE users; --",
            "1; DELETE FROM logs; --",
        ],
    ),
    "time_based_blind": BoundaryProfile(
        name="Time-Based Blind SQL Injection",
        description="Inference-based SQLi via timing",
        test_values=[
            "' AND SLEEP(5) --",
            "1' AND (SELECT * FROM (SELECT(SLEEP(5)))a) --",
        ],
    ),
    "comment_tricks": BoundaryProfile(
        name="Comment & Encoding Tricks",
        description="Bypass filters with encoding",
        test_values=[
            "' /*! OR 1=1 */ --",
            "' /*!50000OR*/ 1=1 --",
            "' %4f%52 1=1 --",  # URL-encoded OR
        ],
    ),
}

# ============================================================================
# XSS PATTERNS (A03)
# ============================================================================

XSS_PATTERNS = {
    "basic_script": BoundaryProfile(
        name="Basic Script Tag",
        description="Simple <script> injection",
        test_values=[
            "<script>alert('xss')</script>",
            "<script>fetch('/admin')</script>",
        ],
    ),
    "event_handler": BoundaryProfile(
        name="Event Handler Injection",
        description="Inject via HTML attributes",
        test_values=[
            '<img src=x onerror="alert(1)">',
            '<svg onload="alert(\'xss\')">',
            '<body onload="fetch(\'/steal\')">',
        ],
    ),
    "html_entity": BoundaryProfile(
        name="HTML Entity Bypass",
        description="Bypass simple encoding",
        test_values=[
            "&lt;script&gt;alert(1)&lt;/script&gt;",
            "&#60;script&#62;alert(1)&#60;/script&#62;",
        ],
    ),
    "javascript_uri": BoundaryProfile(
        name="JavaScript URI",
        description="Execute JS via URI schemes",
        test_values=[
            '<a href="javascript:alert(1)">click</a>',
            '<iframe src="javascript:alert(1)"></iframe>',
        ],
    ),
}

# ============================================================================
# PATH TRAVERSAL (A01)
# ============================================================================

PATH_TRAVERSAL_PATTERNS = {
    "directory_escape": BoundaryProfile(
        name="Directory Escape",
        description="Traverse with ../ sequences",
        test_values=[
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",  # Bypass filter
        ],
    ),
    "null_byte": BoundaryProfile(
        name="Null Byte Injection",
        description="Bypass extension check with %00",
        test_values=[
            "config.php%00.txt",
            "admin.aspx%00.jpg",
        ],
    ),
    "url_encoding": BoundaryProfile(
        name="URL Encoding Bypass",
        description="Double-encoded traversal",
        test_values=[
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # Double-encoded ../
            "%252e%252e%252fetc%252fpasswd",  # Triple-encoded
        ],
    ),
}

# ============================================================================
# AUTHENTICATION BYPASS (A07)
# ============================================================================

AUTH_BYPASS_PATTERNS = {
    "default_credentials": BoundaryProfile(
        name="Default Credentials",
        description="Common default usernames/passwords",
        test_values=[
            {"username": "admin", "password": "admin"},
            {"username": "root", "password": "root"},
            {"username": "test", "password": "test"},
        ],
    ),
    "sql_injection": BoundaryProfile(
        name="SQL Injection in Auth",
        description="Bypass login with SQLi",
        test_values=[
            {"username": "admin' --", "password": "anything"},
            {"username": "' OR '1'='1", "password": "' OR '1'='1"},
        ],
    ),
    "generic_error": BoundaryProfile(
        name="Generic Error Messages",
        description="Check if error reveals user existence",
        test_values=[
            {"username": "nonexistent@example.com", "password": "wrong"},
            {"username": "admin@example.com", "password": "wrong"},
        ],
    ),
}

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


# ============================================================================
# GENERATION RATIO PROFILES
# ============================================================================

TEST_GENERATION_RATIO = {
    "positive": 0.2,  # 20% Happy path
    "negative": 0.35,  # 35% Input validation failures
    "boundary": 0.20,  # 20% Edge cases
    "security": 0.25,  # 25% Security/OWASP tests
}

# Total must equal 1.0, enforces diversity


def get_boundary_value(constraint_name: str, limit_value: int = None) -> Any:
    """Compute boundary value based on constraint and limit.
    
    Args:
        constraint_name: e.g., "max_string", "int32_overflow"
        limit_value: The declared limit (e.g., 255 for max string length)
    
    Returns:
        Appropriate boundary test value
    """
    if constraint_name == "string_max_valid" and limit_value:
        return "a" * limit_value
    elif constraint_name == "string_max_overflow" and limit_value:
        return "a" * (limit_value + 1)
    elif constraint_name == "string_extreme_overflow":
        return "a" * 10000
    elif constraint_name == "int32_overflow":
        return 2147483648
    else:
        return None
