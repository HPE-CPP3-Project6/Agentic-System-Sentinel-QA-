"""Mentor NFR §2.4 — Security (NFR 8–10)."""

from __future__ import annotations

from samples.mentor_requirements._types import MentorStory

STORY = (
    "As a security-conscious operator, I want credentials hashed, tenant isolation "
    "enforced, and inputs sanitized against injection, so that user data stays protected."
)

ACS = [
    "User passwords must be stored as bcrypt hashes — GET /register responses and UserOut schemas must never include password or hashed_password fields (NFR 8).",
    "GET /tasks/{task_id} for another user's task id must return HTTP 404, enforcing per-user isolation (NFR 9).",
    "POST /tasks/ with HTML/script in title or description must persist sanitized text without executable markup in GET responses (NFR 10).",
    "Authenticated SQLi-style payloads in path or query parameters must not produce database error strings in HTTP responses (NFR 10, A03).",
]

STORY_ENTRY: MentorStory = {
    "story": STORY,
    "acs": ACS,
    "title": "Security (NFR 8–10)",
    "story_id": "REQ-NFR-04",
    "module": "Security",
}
