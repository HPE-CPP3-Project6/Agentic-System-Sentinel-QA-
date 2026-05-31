"""Mentor FR §1.10 — Search (FR 39–41)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a user, I want to search tasks by title with case-insensitive, dynamic "
    "filtering, so that I can quickly find specific items as I type."
)

ACS = [
    "The task list search by title may be implemented client-side in the React dashboard or server-side on GET /tasks/ — tests must target the layer grounded in retrieved source (FR 39).",
    "Search matching must be case-insensitive: queries differing only by letter case must return the same matching tasks (FR 40).",
    "Search results must update as the user types without requiring a separate submit action — assert on the frontend filter behavior if search is client-side (FR 41).",
    "If search is client-side only, backend SQLi probes against GET /tasks/ must not be emitted as false injection tests (Rule 10b).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Task Search (FR 39–41)",
    "story_id": "REQ-FR-10",
    "module": "TaskSearch",
}
