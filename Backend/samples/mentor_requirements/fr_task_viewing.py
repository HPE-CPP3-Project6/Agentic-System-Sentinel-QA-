"""Mentor FR §1.4 — Task Viewing (FR 16–18)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want to view my tasks in a list with clear active vs completed "
    "differentiation and full detail fields, so that I can understand my workload at a glance."
)

ACS = [
    "GET /tasks/ as an authenticated user must return HTTP 200 with a paginated list of the caller's non-deleted tasks (FR 16).",
    "Each task item in GET /tasks/ must expose status (Active or Completed) so the client can differentiate completed vs active tasks (FR 17).",
    "GET /tasks/{task_id} for an owned task must return HTTP 200 with title, priority, due_date, and status fields (FR 18).",
    "GET /tasks/ without authentication must return HTTP 401.",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Viewing (FR 16–18)",
    "story_id": "REQ-FR-04",
    "module": "TaskViewing",
}
