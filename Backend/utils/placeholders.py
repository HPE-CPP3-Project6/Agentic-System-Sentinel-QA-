"""Length-precise and time-relative placeholders for generated test data.

Gemini miscounts characters when asked to emit strings of a specific length,
so the Generator emits placeholders that the runtime expands deterministically.

String placeholders (expanded at Generator normalize time):
    <STRING:len=N>                  -> N alphanumeric chars
    <STRING:len=N,chars=alpha>      -> N ASCII letters
    <STRING:len=N,chars=digits>     -> N digits

Datetime placeholders (expanded at pytest runtime so dates stay in the future):
    <DATETIME:future:Nd>            -> UTC ISO8601 Z, N days from now
    <DATETIME:future:Nh>            -> UTC ISO8601 Z, N hours from now
    <TODAY_ISO_UTC>                 -> alias for <DATETIME:future:1d>
"""

from __future__ import annotations

import re
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

_STRING_RE = re.compile(r"<STRING:len=(\d+)(?:,chars=(\w+))?>")
_DATETIME_FUTURE_D_RE = re.compile(r"<DATETIME:future:(\d+)d>", re.IGNORECASE)
_DATETIME_FUTURE_H_RE = re.compile(r"<DATETIME:future:(\d+)h>", re.IGNORECASE)
_TODAY_ISO_UTC_RE = re.compile(r"<TODAY_ISO_UTC>", re.IGNORECASE)

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


def _iso_utc_z(dt: datetime) -> str:
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _inflate_datetime_text(text: str, *, now: Optional[datetime] = None) -> str:
    anchor = now or datetime.now(timezone.utc)

    def _future_days(match: re.Match[str]) -> str:
        days = max(1, int(match.group(1)))
        return _iso_utc_z(anchor + timedelta(days=days))

    def _future_hours(match: re.Match[str]) -> str:
        hours = max(1, int(match.group(1)))
        return _iso_utc_z(anchor + timedelta(hours=hours))

    text = _DATETIME_FUTURE_D_RE.sub(_future_days, text)
    text = _DATETIME_FUTURE_H_RE.sub(_future_hours, text)
    text = _TODAY_ISO_UTC_RE.sub(lambda _m: _iso_utc_z(anchor + timedelta(days=1)), text)
    return text


def _inflate_text(text: str, *, expand_datetime: bool = False, now: Optional[datetime] = None) -> str:
    if expand_datetime:
        text = _inflate_datetime_text(text, now=now)
    return _STRING_RE.sub(
        lambda m: _gen_string(int(m.group(1)), m.group(2) or "alnum"),
        text,
    )


def inflate_placeholders(
    value: Any,
    *,
    expand_datetime: bool = False,
    now: Optional[datetime] = None,
) -> Any:
    """Recursively replace placeholders inside str / dict / list structures."""
    if isinstance(value, str):
        return _inflate_text(value, expand_datetime=expand_datetime, now=now)
    if isinstance(value, dict):
        return {
            k: inflate_placeholders(v, expand_datetime=expand_datetime, now=now)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            inflate_placeholders(v, expand_datetime=expand_datetime, now=now)
            for v in value
        ]
    return value


def inflate_runtime_placeholders(value: Any, *, now: Optional[datetime] = None) -> Any:
    """Expand STRING + DATETIME placeholders — call from generated pytest at request time."""
    return inflate_placeholders(value, expand_datetime=True, now=now)
