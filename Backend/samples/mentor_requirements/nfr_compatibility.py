"""Mentor NFR §2.7 — Compatibility (NFR 16–17)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a team using common stacks, I want the frontend and backend built on "
    "widely supported frameworks and runtimes."
)

ACS = [
    "The frontend must use React with Vite as declared in package.json (NFR 16).",
    "The backend must run on CPython with FastAPI and SQLAlchemy as declared in requirements.txt (NFR 17).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Compatibility (NFR 16–17)",
    "story_id": "REQ-NFR-07",
    "module": "Compatibility",
}
