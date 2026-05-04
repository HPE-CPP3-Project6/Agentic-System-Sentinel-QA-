"""Length-precise string placeholders for generated test data.

Gemini miscounts characters when asked to emit strings of a specific length,
so the Generator emits a placeholder of the form

    <STRING:len=N>            -> N alphanumeric chars
    <STRING:len=N,chars=alpha>  -> N ASCII letters
    <STRING:len=N,chars=digits> -> N digits

and this module expands it deterministically before the TestCase is persisted.
Deterministic output means re-running the pipeline produces the same payloads,
which matters for reproducible Security+Compiler / Executor runs.
"""

from __future__ import annotations

import re
import string
from typing import Any

_STRING_RE = re.compile(r"<STRING:len=(\d+)(?:,chars=(\w+))?>")

_ALPHABETS = {
    "alpha": string.ascii_letters,
    "alnum": string.ascii_letters + string.digits,
    "digits": string.digits,
    "ascii": string.ascii_letters + string.digits,
}


def _gen_string(length: int, alphabet_name: str = "alnum") -> str:
    if length <= 0:
        return ""
    alpha = _ALPHABETS.get(alphabet_name, _ALPHABETS["alnum"])
    n = len(alpha)
    return "".join(alpha[i % n] for i in range(length))


def _inflate_text(text: str) -> str:
    def sub(m: re.Match[str]) -> str:
        return _gen_string(int(m.group(1)), m.group(2) or "alnum")
    return _STRING_RE.sub(sub, text)


def inflate_placeholders(value: Any) -> Any:
    """Recursively replace <STRING:len=N[,chars=...]> placeholders inside any
    JSON-like structure (str / dict / list). Other types are returned as-is.
    """
    if isinstance(value, str):
        return _inflate_text(value)
    if isinstance(value, dict):
        return {k: inflate_placeholders(v) for k, v in value.items()}
    if isinstance(value, list):
        return [inflate_placeholders(v) for v in value]
    return value
