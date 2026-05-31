"""Mentor FR §1.6 — Task Completion (FR 24–26)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want to mark tasks completed and revert them to active, "
    "with clear visual status in the UI, so that I can track finished work."
)

ACS = [
    "PATCH /tasks/{task_id} setting status to Completed must return HTTP 200 and persist status=Completed (FR 24).",
    "PATCH /tasks/{task_id} setting status back to Active must return HTTP 200 and persist status=Active (FR 25).",
    "GET /tasks/?status=Completed must return only completed tasks for the authenticated user (FR 24, FR 26 API layer).",
    "Visual strikethrough or color change for completed tasks is implemented in the React dashboard JSX — assert via UI/E2E or document as coverage gap (FR 26).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Completion (FR 24–26)",
    "story_id": "REQ-FR-06",
    "module": "TaskCompletion",
}
