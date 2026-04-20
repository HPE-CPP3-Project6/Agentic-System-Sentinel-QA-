"""Tolerant JSON extraction for LLM responses.

Order of attempts:
1. Extract text from LLM response (handle string, list, or structured content)
2. Strip ```json fences → json.loads
3. Regex-extract the outermost {...} and retry
4. json_repair.loads — handles unescaped quotes / newlines / trailing commas

If all three fail, the original JSONDecodeError is raised so callers can
log the raw payload to coverage_gaps / metadata.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from json_repair import repair_json

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_text_from_response(raw: Any) -> str:
    """Extract text from various response formats.
    
    Handles:
    - str: returned as-is
    - dict: returns 'content' or 'text' field if present
    - list: extracts text from content blocks or first dict with 'text'
    - objects with .text attribute: returns that
    """
    if isinstance(raw, str):
        return raw
    
    if isinstance(raw, dict):
        # Try common fields
        if "content" in raw:
            content = raw["content"]
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Recursively extract from list
                return _extract_text_from_response(content)
        if "text" in raw:
            return raw["text"]
        # If it's a single-item dict, try extracting from it
        raise ValueError(f"No text/content field in dict: {raw}")
    
    if isinstance(raw, list):
        # Handle list of content blocks
        for item in raw:
            # Try to extract text from each item
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                if "text" in item:
                    return item["text"]
                if "content" in item:
                    return _extract_text_from_response(item["content"])
            # Try to access .text attribute (for LangChain content blocks)
            if hasattr(item, "text"):
                return item.text
        raise ValueError(f"No text found in list response: {raw}")
    
    # Try attribute access
    if hasattr(raw, "text"):
        return raw.text
    if hasattr(raw, "content"):
        return _extract_text_from_response(raw.content)
    
    raise ValueError(f"Cannot extract text from response type {type(raw)}: {raw}")


def stringify_response(raw: Any) -> str:
    """Convert any response format to a string representation.
    
    Safe version of _extract_text_from_response that returns a string
    even if extraction fails (useful for logging/metadata).
    """
    try:
        return _extract_text_from_response(raw)
    except (ValueError, AttributeError):
        # Fallback: convert to string representation
        if isinstance(raw, str):
            return raw
        if isinstance(raw, (dict, list)):
            return json.dumps(raw)
        return str(raw)


def parse_llm_json(raw: str | list | dict | Any) -> Dict[str, Any]:
    """Parse JSON from LLM response, handling various formats."""
    
    # First, extract text from the response
    try:
        text = _extract_text_from_response(raw)
    except ValueError as e:
        raise ValueError(f"Failed to extract text from response: {e}") from e
    
    # Clean up text
    text = text.strip()
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
    raise json.JSONDecodeError("json_repair could not recover a JSON object", text, 0)
