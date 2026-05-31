"""Mentor NFR §2.3 — Reliability (NFR 6–7)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want the application to keep my data safe during normal use "
    "and handle bad inputs without crashing."
)

ACS = [
    "A successful POST /tasks/ followed by server restart (or new DB session) must still return the task on subsequent GET /tasks/{task_id} (NFR 6).",
    "POST /tasks/ with malformed JSON must return HTTP 422, not HTTP 500 with an unhandled exception (NFR 7).",
    "POST /tasks/ with invalid priority enum must return HTTP 422 with a structured error body, not a stack trace in the response (NFR 7).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Reliability (NFR 6–7)",
    "story_id": "REQ-NFR-03",
    "module": "Reliability",
}
