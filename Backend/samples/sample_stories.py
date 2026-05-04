"""Bundled sample user stories + acceptance criteria.

Two flavours:
  * Functional demo (organization, filter) — used to smoke-test the Critic on
    stories where OWASP mapping should remain mostly empty.
  * Security-focused demos (login, search, permissions, ratelimit, data
    export) — intentionally written with OWASP-triggering anti-patterns so
    the Critic fires the appropriate A01 / A03 / A04 / A07 mappings and the
    downstream Security+Compiler / Executor get something to attack.

These strings are fixtures, not product data. Keeping them out of
`agents/critic.py` means the agent module ships only production logic.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class SampleStory(TypedDict):
    story: str
    acs: List[str]
    title: str
    story_id: str
    module: str


# --------------------------------------------------------------------------- #
# Functional stories                                                          #
# --------------------------------------------------------------------------- #

SAMPLE_ORGANIZATION_STORY = (
    "As an HPE tenant administrator, I want to create a new Organization by "
    "submitting its legal name and primary contact email through the admin portal, "
    "so that downstream services can provision isolated resources for that tenant."
)

SAMPLE_ORGANIZATION_ACS: List[str] = [
    "The legal name field must reject empty strings and strings longer than 255 characters.",
    "Submitting a duplicate legal name must return a 409 Conflict without creating a record.",
    "On success the API must return the new organization_id and persist the contact email.",
]


SAMPLE_FILTER_STORY = (
    "As a user, I want to filter my tasks by priority so that I can focus on "
    "high-priority items first."
)

SAMPLE_FILTER_ACS: List[str] = [
    "The filter dropdown must contain: All, Low, Medium, High.",
    "Selecting 'High' must hide all Low and Medium priority tasks immediately.",
    "Selecting 'All' must reset the view to show all tasks regardless of priority.",
]


# --------------------------------------------------------------------------- #
# Security-focused stories (deliberately vulnerable ACs)                      #
# --------------------------------------------------------------------------- #

SAMPLE_LOGIN_STORY = (
    "As a user, I want to log in to my account by entering my username and password, "
    "so that I can access my personalized dashboard and task list."
)

SAMPLE_LOGIN_ACS: List[str] = [
    "The login form must accept any username and password without length restrictions.",
    "Failed login attempts must allow unlimited retries with no delays or account lockout.",
    "The system must accept passwords containing special characters like SQL wildcards (%) and semicolons (;).",
    "On successful login, the session token should be transmitted in plaintext via HTTP.",
    "The system should display the user's full name and email on an unencrypted page after login.",
]


SAMPLE_SEARCH_STORY = (
    "As a user, I want to search for tasks by typing a search query into a text field "
    "so that I can quickly find specific tasks by name or description."
)

SAMPLE_SEARCH_ACS: List[str] = [
    "The search field must accept and pass user input directly to the database query without sanitization.",
    "Search results should display raw data including internal IDs and system fields.",
    "The search feature should work across all user records, regardless of permissions.",
    "If the search input contains special characters (like ' or --), they must be included in the SQL query as-is.",
    "Error messages should display the full SQL query and database error details to aid debugging.",
]


SAMPLE_PERMISSIONS_STORY = (
    "As a team lead, I want to view all team members' tasks and edit their assignments "
    "so that I can manage workload and reassign tasks as needed."
)

SAMPLE_PERMISSIONS_ACS: List[str] = [
    "The system must allow any authenticated user to view all other users' tasks via the API.",
    "The API endpoint /tasks/{task_id} should not validate user ownership before returning data.",
    "Editing a task should only verify that the user is authenticated, not that they have permission.",
    "Users should be able to modify task_owner to any user ID without approval or audit logging.",
    "Permission checks should be implemented only on the frontend; backend should trust all authenticated requests.",
]


SAMPLE_RATELIMIT_STORY = (
    "As a system, I want to allow users to submit multiple login attempts in rapid succession "
    "so that users can quickly retry if they mistyped their password."
)

SAMPLE_RATELIMIT_ACS: List[str] = [
    "The login endpoint must accept unlimited requests from a single IP address without throttling.",
    "Failed login attempts must not trigger any temporary account lockout or exponential delays.",
    "The API must not implement rate limiting on password reset or account recovery endpoints.",
    "Users must be able to trigger password reset emails repeatedly to flood other users' mailboxes.",
    "There must be no CAPTCHA or challenge-response mechanism on repeated failed attempts.",
]


SAMPLE_DATAEXPOSURE_STORY = (
    "As a power user, I want to export all data from the application in bulk "
    "so that I can perform offline analysis and create backups."
)

SAMPLE_DATAEXPOSURE_ACS: List[str] = [
    "The export feature must include all records in the database, including other users' private data.",
    "The exported file must be transmitted unencrypted and stored with world-readable permissions.",
    "The bulk export endpoint should accept a user_id parameter that can be modified to export any user's data.",
    "Audit logs must not be generated for data export operations.",
    "The API should not verify that the exported data belongs to the requesting user.",
]


# --------------------------------------------------------------------------- #
# Registry (consumed by run_critic_generator.py)                              #
# --------------------------------------------------------------------------- #

SAMPLE_STORIES: Dict[str, SampleStory] = {
    "filter": {
        "story": SAMPLE_FILTER_STORY,
        "acs": SAMPLE_FILTER_ACS,
        "title": "Filter by Priority",
        "story_id": "US-001",
        "module": "TaskManager",
    },
    "org": {
        "story": SAMPLE_ORGANIZATION_STORY,
        "acs": SAMPLE_ORGANIZATION_ACS,
        "title": "Create Organization",
        "story_id": "ORG-001",
        "module": "Organization",
    },
    "login": {
        "story": SAMPLE_LOGIN_STORY,
        "acs": SAMPLE_LOGIN_ACS,
        "title": "User Login",
        "story_id": "AUTH-001",
        "module": "Authentication",
    },
    "search": {
        "story": SAMPLE_SEARCH_STORY,
        "acs": SAMPLE_SEARCH_ACS,
        "title": "Task Search",
        "story_id": "SEARCH-001",
        "module": "Search",
    },
    "perms": {
        "story": SAMPLE_PERMISSIONS_STORY,
        "acs": SAMPLE_PERMISSIONS_ACS,
        "title": "Team Permissions",
        "story_id": "AUTHZ-001",
        "module": "Authorization",
    },
    "ratelimit": {
        "story": SAMPLE_RATELIMIT_STORY,
        "acs": SAMPLE_RATELIMIT_ACS,
        "title": "Rate Limiting",
        "story_id": "RATELIMIT-001",
        "module": "Security",
    },
    "dataexport": {
        "story": SAMPLE_DATAEXPOSURE_STORY,
        "acs": SAMPLE_DATAEXPOSURE_ACS,
        "title": "Data Export",
        "story_id": "DATAEXP-001",
        "module": "DataHandling",
    },
}
