"""Mentor NFR §2.2 — Performance (NFR 4–5)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user with a large task list, I want create, update, delete, and filter "
    "operations to complete quickly, so that the app stays responsive."
)

ACS = [
    "POST /tasks/, PATCH /tasks/{task_id}, DELETE /tasks/{task_id}, and GET /tasks/ with filters must each complete within 1 second under normal local load (NFR 4 — timing assertion or documented gap without load harness).",
    "GET /tasks/?limit=50 with at least 1,000 seeded tasks for one user must return HTTP 200 within 1 second (NFR 5 — requires seed fixture or coverage gap).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Performance (NFR 4–5)",
    "story_id": "REQ-NFR-02",
    "module": "Performance",
}
