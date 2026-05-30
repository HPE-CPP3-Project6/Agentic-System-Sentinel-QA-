"""Path-template matching helpers.

Single source of truth for "does the request path the test sent match the
endpoint the SurfaceMap bound this REQ to?" — used by Generator validation,
Compiler mutation gating, and the Classifier's tier-0 off-target check.

Normalization rules:
  - Trailing slash is irrelevant: /tasks/ == /tasks.
  - {param} segments in templates match any non-empty actual segment.
  - Length must agree — /tasks does NOT match /tasks/{task_id}.
  - Case-sensitive on path segments (FastAPI is, so we mirror it).

Without this, a binding for /tasks/{task_id} would not match the request
/tasks/550e8400-... (false off-target), and /tasks/ vs /tasks would split
the same endpoint into two buckets (false mismatch). Both were observed
during the Layer-A scoping.
"""

from __future__ import annotations

from typing import Iterable, List


def _normalize(path: str) -> str:
    """Strip trailing slash; ensure leading slash. Empty → '/'."""
    if not path:
        return "/"
    p = "/" + path.strip("/")
    return p if p else "/"


def _path_template_match(actual: str, template: str) -> bool:
    """Match `actual` against a FastAPI-style template that may include
    `{param}` segments.

    Examples:
      _path_template_match("/tasks", "/tasks/")                        -> True
      _path_template_match("/tasks/abc", "/tasks/{task_id}")           -> True
      _path_template_match("/tasks",     "/tasks/{task_id}")           -> False
      _path_template_match("/tasks/abc", "/tasks/")                    -> False
      _path_template_match("/tasks/abc/share", "/tasks/{task_id}")     -> False
    """
    if not template:
        return False
    a_segs = _normalize(actual).split("/")
    t_segs = _normalize(template).split("/")
    if len(a_segs) != len(t_segs):
        return False
    for a_seg, t_seg in zip(a_segs, t_segs):
        if t_seg.startswith("{") and t_seg.endswith("}"):
            if not a_seg:  # template requires a value here
                return False
            continue
        if a_seg != t_seg:
            return False
    return True


def _paths_match_any(actual: str, templates: Iterable[str]) -> bool:
    """True iff `actual` matches at least one of the supplied templates."""
    return any(_path_template_match(actual, t) for t in templates)


def _normalize_for_display(path: str) -> str:
    """Stable form used in evidence strings / log messages."""
    return _normalize(path)
