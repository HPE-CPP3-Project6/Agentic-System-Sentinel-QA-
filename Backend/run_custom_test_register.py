"""Second custom-story test harness — user registration.

Exercises the pipeline on a WRITE-intent story with Pydantic validators,
storage-width constraints, and a mixed OWASP profile (A03 + A04 + A08).
"""
from __future__ import annotations

import sys

from bootstrap import configure_caches

configure_caches()

from run_critic_generator import build_two_agent_graph, _print_state  # noqa: E402
from state import ProjectState  # noqa: E402

CUSTOM_STORY = """
As a new visitor, I want to register for a Smart Task Manager account using my
email and a password, so that I can start managing my personal tasks securely.
"""

CUSTOM_ACS = [
    "Given a valid email address and a password that meets the complexity policy, When the user submits the registration request, Then the system creates a new account and returns 201 Created with the user's id, email, and created_at — never the password or password hash.",
    "Given an email address that is already registered, When the user submits the registration request, Then the system returns 409 Conflict with a clear error message and does NOT create a duplicate account.",
    "Given a password shorter than 8 characters, When the user submits, Then the system rejects the request with 422 Unprocessable Entity.",
    "Given a password that lacks an uppercase letter or a digit, When the user submits, Then the system rejects the request with 422 and a message naming the missing complexity rule.",
    'Given an email field containing a script payload (e.g., "<script>alert(1)</script>@x.com"), When the user submits, Then the payload must be rejected by validation, and any response echo must be safely encoded so no script executes in the browser.',
]


def main() -> int:
    app = build_two_agent_graph()
    initial = ProjectState(
        user_story=CUSTOM_STORY.strip(),
        acceptance_criteria=CUSTOM_ACS,
        story_title="New User Registration",
        story_id="REGISTER-001",
        module="Authentication",
    )
    print("Running Critic -> Generator on CUSTOM SAMPLE (User Registration)...")
    final = app.invoke(initial)
    final_state = ProjectState.model_validate(final) if not isinstance(final, ProjectState) else final
    _print_state(final_state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
