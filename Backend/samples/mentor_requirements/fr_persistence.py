"""Mentor FR §1.11 — Persistence (FR 42–44)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want my tasks saved across sessions in durable storage, "
    "so that data survives browser restarts and application reloads."
)

ACS = [
    "POST /tasks/ followed by GET /tasks/{task_id} after a new HTTP session (same user JWT) must return HTTP 200 with the persisted task (FR 42).",
    "Task data must be stored in SQLite via SQLAlchemy — not only browser localStorage (FR 43 backend path).",
    "GET /tasks/ on application startup after prior task creation must return previously saved tasks for the authenticated user (FR 44).",
    "JWT or session token persistence in browser localStorage is a frontend concern — document separately if asserting client reload behavior (FR 44 UI layer).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Persistence (FR 42–44)",
    "story_id": "REQ-FR-11",
    "module": "TaskPersistence",
}
