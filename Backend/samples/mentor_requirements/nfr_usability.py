"""Mentor NFR §2.1 — Usability (NFR 1–3)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a non-technical user, I want a simple, intuitive, responsive interface "
    "on desktop and mobile, so that I can manage tasks without training."
)

ACS = [
    "The dashboard must render a task list and primary actions (create, filter) without requiring more than three clicks to add a task (NFR 1 — subjective; document heuristic or UI test).",
    "Form labels for login, register, and task creation must use plain language visible in retrieved JSX (NFR 2).",
    "The React layout must use responsive CSS so primary controls remain usable at mobile viewport widths (NFR 3 — DOM/CSS assertion or coverage gap).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Usability (NFR 1–3)",
    "story_id": "REQ-NFR-01",
    "module": "Usability",
}
