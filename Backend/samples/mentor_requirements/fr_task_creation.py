"""Mentor FR §1.2 — Task Creation (FR 6–10)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a task owner, I want to create a new task with title, description, "
    "priority, due date, and status, so that each item is tracked with a "
    "unique id and sensible defaults."
)

ACS = [
    "POST /tasks/ as an authenticated user with valid fields must return HTTP 201 and create a task (FR 6).",
    "The HTTP 201 response body must include title, description, priority, due_date, status, created_at, and a unique task id (FR 7, FR 8).",
    "POST /tasks/ without a priority field must persist priority as Medium (FR 9).",
    "POST /tasks/ without an explicit due_date must either accept null due_date or apply the product default documented in TaskCreate (FR 10).",
    "POST /tasks/ without authentication must return HTTP 401 (precondition for FR 6).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Creation (FR 6–10)",
    "story_id": "REQ-FR-02",
    "module": "TaskCreation",
}
