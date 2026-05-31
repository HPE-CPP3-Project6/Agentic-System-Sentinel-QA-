"""Mentor FR §1.7 — Task Deletion (FR 27–29)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a task owner, I want to delete tasks with confirmation and optional undo, "
    "so that I can remove items safely without accidental data loss."
)

ACS = [
    "DELETE /tasks/{task_id} for an owned active task must return HTTP 200 and soft-delete the task (FR 27).",
    "GET /tasks/{task_id} after soft-delete must return HTTP 404 (FR 27, lifecycle).",
    "DELETE /tasks/{task_id} for a task owned by another user must return HTTP 404 (FR 4).",
    "A confirmation dialog before delete is a frontend UX requirement — document as UI coverage gap unless a server-side confirm flag exists (FR 28).",
    "Restoring a recently deleted task requires an undo/restore endpoint or soft-delete reversal — document gap if not implemented (FR 29).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Deletion (FR 27–29)",
    "story_id": "REQ-FR-07",
    "module": "TaskDeletion",
}
