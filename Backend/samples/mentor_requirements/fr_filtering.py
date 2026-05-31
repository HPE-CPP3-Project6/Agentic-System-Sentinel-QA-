"""Mentor FR §1.8 — Filtering (FR 30–34)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want to filter tasks by priority, status, and due-date bucket, "
    "including multiple filters at once and a reset, so that I can focus on the "
    "right subset of work."
)

ACS = [
    "GET /tasks/?priority=High must return HTTP 200 containing only High-priority tasks for the authenticated user (FR 30).",
    "GET /tasks/?status=Active must return HTTP 200 containing only Active tasks (FR 31).",
    "GET /tasks/?date_filter=Overdue must return HTTP 200 with tasks whose due dates are before today (FR 32).",
    "GET /tasks/?priority=High&status=Active must apply both filters with logical AND (FR 33).",
    "GET /tasks/ without filter query params must return the full active task set for the user, equivalent to resetting filters (FR 34).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Filtering (FR 30–34)",
    "story_id": "REQ-FR-08",
    "module": "TaskFiltering",
}
