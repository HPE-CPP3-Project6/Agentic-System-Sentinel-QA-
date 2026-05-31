"""Mentor FR §1.3 — Task Validation (FR 11–15)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a product owner, I want invalid task inputs rejected with clear errors, "
    "so that users cannot create malformed or unsafe task records."
)

ACS = [
    "POST /tasks/ with a missing or empty title must return HTTP 422 (FR 11).",
    "POST /tasks/ with invalid enum values for priority or status must return HTTP 422 with a validation detail message (FR 12).",
    "POST /tasks/ with a due_date in the past must return HTTP 422 (FR 13).",
    "POST /tasks/ with a description longer than 200 characters must return HTTP 422 (FR 14).",
    "POST /tasks/ with a duplicate title for the same user must either return HTTP 409 or HTTP 201 if duplicate titles are allowed — behavior must match the implemented policy (FR 15).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Validation (FR 11–15)",
    "story_id": "REQ-FR-03",
    "module": "TaskValidation",
}
