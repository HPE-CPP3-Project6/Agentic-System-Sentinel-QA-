"""Mentor NFR §2.6 — Portability (NFR 14–15)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a student developer, I want the app to run in modern browsers on a "
    "standard laptop without special hardware."
)

ACS = [
    "The React frontend must load and render the dashboard in Chromium-based browsers (NFR 14 — manual/E2E or gap).",
    "The FastAPI backend must start with uvicorn on localhost using Python 3.10+ without GPU or enterprise infrastructure (NFR 15).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Portability (NFR 14–15)",
    "story_id": "REQ-NFR-06",
    "module": "Portability",
}
