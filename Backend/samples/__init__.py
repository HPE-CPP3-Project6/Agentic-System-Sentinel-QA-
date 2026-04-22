"""Bundled sample user stories + acceptance criteria for smoke runs.

These fixtures drive `run_critic_generator.py` and ad-hoc manual testing.
They are intentionally kept OUT of `agents/` so agent modules carry only
production logic. Import paths:

    from samples import SAMPLE_STORIES                 # registry dict
    from samples.sample_stories import SAMPLE_LOGIN_ACS  # direct constants
"""

from .sample_stories import (
    SAMPLE_DATAEXPOSURE_ACS,
    SAMPLE_DATAEXPOSURE_STORY,
    SAMPLE_FILTER_ACS,
    SAMPLE_FILTER_STORY,
    SAMPLE_LOGIN_ACS,
    SAMPLE_LOGIN_STORY,
    SAMPLE_ORGANIZATION_ACS,
    SAMPLE_ORGANIZATION_STORY,
    SAMPLE_PERMISSIONS_ACS,
    SAMPLE_PERMISSIONS_STORY,
    SAMPLE_RATELIMIT_ACS,
    SAMPLE_RATELIMIT_STORY,
    SAMPLE_SEARCH_ACS,
    SAMPLE_SEARCH_STORY,
    SAMPLE_STORIES,
)

__all__ = [
    "SAMPLE_DATAEXPOSURE_ACS",
    "SAMPLE_DATAEXPOSURE_STORY",
    "SAMPLE_FILTER_ACS",
    "SAMPLE_FILTER_STORY",
    "SAMPLE_LOGIN_ACS",
    "SAMPLE_LOGIN_STORY",
    "SAMPLE_ORGANIZATION_ACS",
    "SAMPLE_ORGANIZATION_STORY",
    "SAMPLE_PERMISSIONS_ACS",
    "SAMPLE_PERMISSIONS_STORY",
    "SAMPLE_RATELIMIT_ACS",
    "SAMPLE_RATELIMIT_STORY",
    "SAMPLE_SEARCH_ACS",
    "SAMPLE_SEARCH_STORY",
    "SAMPLE_STORIES",
]
