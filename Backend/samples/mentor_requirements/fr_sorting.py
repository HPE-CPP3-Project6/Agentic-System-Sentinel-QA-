"""Mentor FR §1.9 — Sorting (FR 35–38)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want to sort tasks by due date, priority, or creation date "
    "in ascending or descending order, so that I can organize my list effectively."
)

ACS = [
    "GET /tasks/?sort_by=due_date&sort_order=asc must return HTTP 200 with tasks ordered by due date ascending (FR 35, FR 38).",
    "GET /tasks/?sort_by=not_a_field&sort_order=desc must return HTTP 422 or ignore invalid sort fields per API contract (FR 35 negative).",
    "GET /tasks/?sort_by=priority&sort_order=desc must return HTTP 200 with High before Medium before Low (FR 36, FR 38).",
    "GET /tasks/?sort_by=created_at&sort_order=asc must return HTTP 200 ordered by creation timestamp (FR 37, FR 38).",
    "GET /tasks/?sort_by=due_date&sort_order=desc must return HTTP 200 with reverse due-date ordering (FR 38).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Sorting (FR 35–38)",
    "story_id": "REQ-FR-09",
    "module": "TaskSorting",
}
