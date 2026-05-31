"""Mentor-provided FR/NFR requirement stories for pipeline smoke runs.

Each module under this package maps one section of the mentor requirements
document to a user story + acceptance criteria list consumable by main.py:

    python main.py --mode post_code req-fr-filter
    python main.py --mode post_code req-nfr-security

See README.md in this folder for the full key catalog.
"""

from samples.mentor_requirements.registry import (
    FUNCTIONAL_KEYS,
    MENTOR_REQUIREMENT_STORIES,
    MENTOR_STORY_CATALOG,
    NFR_KEYS,
)

__all__ = [
    "FUNCTIONAL_KEYS",
    "MENTOR_REQUIREMENT_STORIES",
    "MENTOR_STORY_CATALOG",
    "NFR_KEYS",
]
