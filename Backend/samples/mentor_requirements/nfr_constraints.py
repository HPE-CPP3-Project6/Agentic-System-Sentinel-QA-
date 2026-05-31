"""Mentor NFR §2.8 — Constraints (NFR 18–20)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a student, I want to run the entire project locally with open-source "
    "tools and without enterprise servers or always-on cloud dependency."
)

ACS = [
    "The application must be runnable on a developer laptop with localhost URLs only — no mandatory enterprise deployment target (NFR 18).",
    "Dependencies in requirements.txt and package.json must be open-source packages installable via pip and npm (NFR 19).",
    "After initial setup and ingest, POST_CODE test execution must work against a locally running API without continuous internet access to cloud LLMs disabled separately via env (NFR 20 — document LLM vs app offline scope).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Constraints (NFR 18–20)",
    "story_id": "REQ-NFR-08",
    "module": "Constraints",
}
