"""Mentor NFR §2.5 — Maintainability (NFR 11–13)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a developer, I want a modular codebase with clear setup documentation, "
    "so that new features can be added safely."
)

ACS = [
    "The backend must separate routers, schemas, models, and auth into distinct modules importable without circular dependencies (NFR 11 — static structure check or coverage gap).",
    "Adding a new task field should require changes only in schemas, models, and router layers — document extension points (NFR 12).",
    "The repository README must document Backend setup, Chroma ingest, and how to run post_code against sample stories (NFR 13).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Maintainability (NFR 11–13)",
    "story_id": "REQ-NFR-05",
    "module": "Maintainability",
}
