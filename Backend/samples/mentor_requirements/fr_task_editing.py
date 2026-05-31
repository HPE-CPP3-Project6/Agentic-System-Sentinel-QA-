"""Mentor FR §1.5 — Task Editing (FR 19–23)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a task owner, I want to edit an existing task's title, description, "
    "priority, and due date with the same validation as creation, so that "
    "updates are safe and auditable."
)

ACS = [
    "PATCH /tasks/{task_id} with valid partial updates must return HTTP 200 and persist the changed fields (FR 19, FR 20).",
    "PATCH /tasks/{task_id} with an empty title must return HTTP 422, matching create-time validation (FR 21).",
    "PATCH /tasks/{task_id} with a past due_date must return HTTP 422 (FR 21, FR 13).",
    "After a successful PATCH, GET /tasks/{task_id} must reflect an updated updated_at timestamp (FR 22).",
    "Discarding unsaved edits is a client-side concern; the API must not mutate a task unless PATCH is called (FR 23 — document as UI/coverage gap if no cancel endpoint exists).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Editing (FR 19–23)",
    "story_id": "REQ-FR-05",
    "module": "TaskEditing",
}
