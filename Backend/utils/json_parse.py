"""Tolerant JSON extraction for LLM responses.

Order of attempts:
1. Strip ```json fences → json.loads
2. Regex-extract the outermost {...} and retry
3. json_repair.loads — handles unescaped quotes / newlines / trailing commas

If all three fail, the original JSONDecodeError is raised so callers can
log the raw payload to coverage_gaps / metadata.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from json_repair import repair_json

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_llm_json(raw: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJ_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            text = match.group(0)

    repaired = repair_json(text, return_objects=True)
    if isinstance(repaired, dict):
        return repaired
    # json_repair returned a non-dict fallback — re-raise a clean error.
    raise json.JSONDecodeError("json_repair could not recover a JSON object", raw, 0)
