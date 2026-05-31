"""OWASP Top 10 (2021) payload library for the Security+Compiler agent.

Scope: authorized security testing within HPE's Sentinel-QA pipeline. Payloads
are intentionally canonical / public-domain so they can be fingerprinted by
defensive tooling during evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Payload:
    value: str
    technique: str
    exploit_target: str
    expected_signal: str


# Keyed by the leading OWASP identifier ("A01", "A03", ...) — callers may pass
# either the short form or the full "A03:2021-Injection" string.
_LIBRARY: Dict[str, List[Payload]] = {
    "A01": [  # Broken Access Control
        Payload(
            value="../../../../etc/passwd",
            technique="Path traversal",
            exploit_target="A01:2021-Broken Access Control",
            expected_signal="400/403 response; no file contents echoed",
        ),
        Payload(
            value="{'role': 'admin'}",
            technique="Mass-assignment / privilege escalation",
            exploit_target="A01:2021-Broken Access Control",
            expected_signal="role field ignored server-side; 200 with unchanged role",
        ),
    ],
    "A02": [  # Cryptographic Failures
        Payload(
            value="http://internal-service/token",
            technique="Downgrade to cleartext channel",
            exploit_target="A02:2021-Cryptographic Failures",
            expected_signal="request refused; enforced TLS",
        ),
    ],
    "A03": [  # Injection (SQLi, XSS, command, NoSQL, ...)
        Payload(
            value="' OR 1=1 --",
            technique="Classic SQL injection (tautology)",
            exploit_target="A03:2021-Injection (SQLi)",
            expected_signal="parameterised query; 400 or unchanged result set",
        ),
        Payload(
            value="'; DROP TABLE organizations; --",
            technique="SQL injection (stacked statement)",
            exploit_target="A03:2021-Injection (SQLi)",
            expected_signal="query rejected; schema intact",
        ),
        Payload(
            value="<script>alert(1)</script>",
            technique="Reflected XSS",
            exploit_target="A03:2021-Injection (XSS)",
            expected_signal="value rendered as escaped text, not executed",
        ),
        Payload(
            value="\"><img src=x onerror=alert(1)>",
            technique="Attribute-break XSS",
            exploit_target="A03:2021-Injection (XSS)",
            expected_signal="attributes escaped; no onerror fires",
        ),
        Payload(
            value="; cat /etc/passwd",
            technique="OS command injection",
            exploit_target="A03:2021-Injection (Command)",
            expected_signal="shell metacharacters rejected / quoted",
        ),
        Payload(
            value="{\"$ne\": null}",
            technique="NoSQL operator injection",
            exploit_target="A03:2021-Injection (NoSQL)",
            expected_signal="operator tokens treated as literal string",
        ),
    ],
    "A04": [  # Insecure Design
        Payload(
            value="A" * 10_000,
            technique="Oversized input / missing length cap",
            exploit_target="A04:2021-Insecure Design",
            expected_signal="413 or 400 before reaching business logic",
        ),
    ],
    "A05": [  # Security Misconfiguration
        Payload(
            value="X-Forwarded-Host: evil.example",
            technique="Host header injection",
            exploit_target="A05:2021-Security Misconfiguration",
            expected_signal="header ignored; no redirect to attacker host",
        ),
    ],
    "A07": [  # Identification & Authentication Failures
        Payload(
            value="admin",
            technique="Default/weak credential probe",
            exploit_target="A07:2021-Authentication Failures",
            expected_signal="401; rate-limited after N attempts",
        ),
    ],
    "A08": [  # Software & Data Integrity Failures
        Payload(
            value="__proto__[isAdmin]=true",
            technique="Prototype pollution",
            exploit_target="A08:2021-Software and Data Integrity Failures",
            expected_signal="payload sanitised; object prototype untouched",
        ),
    ],
    "A10": [  # SSRF
        Payload(
            value="http://169.254.169.254/latest/meta-data/",
            technique="SSRF to cloud metadata",
            exploit_target="A10:2021-Server-Side Request Forgery",
            expected_signal="outbound request blocked; 400/403",
        ),
    ],
}


def _normalise(owasp_id: str) -> str:
    """Accept 'A03', 'A03:2021', or 'A03:2021-Injection' → 'A03'."""
    return owasp_id.strip().split(":")[0].upper()


def get_payloads(owasp_id: str) -> List[Payload]:
    return list(_LIBRARY.get(_normalise(owasp_id), []))
