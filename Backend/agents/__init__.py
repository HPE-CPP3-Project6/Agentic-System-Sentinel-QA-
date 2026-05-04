"""Agent nodes + backward-compatible re-exports of bundled sample stories.

Sample fixtures live in `samples/sample_stories.py`. They are re-exported
here so legacy callers (`from agents import SAMPLE_LOGIN_STORY`) keep
working; new code should import from `samples` directly.
"""

from .critic import critic_node
from .executor import executor_node, needs_healing
from .generator import generator_node
from .security_compiler import security_compiler_node

from samples.sample_stories import (
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
)

__all__ = [
    # Agent nodes
    "critic_node",
    "generator_node",
    "security_compiler_node",
    "executor_node",
    "needs_healing",
    # Sample re-exports (deprecated surface — import from `samples` instead)
    "SAMPLE_ORGANIZATION_STORY",
    "SAMPLE_ORGANIZATION_ACS",
    "SAMPLE_FILTER_STORY",
    "SAMPLE_FILTER_ACS",
    "SAMPLE_LOGIN_STORY",
    "SAMPLE_LOGIN_ACS",
    "SAMPLE_SEARCH_STORY",
    "SAMPLE_SEARCH_ACS",
    "SAMPLE_PERMISSIONS_STORY",
    "SAMPLE_PERMISSIONS_ACS",
    "SAMPLE_RATELIMIT_STORY",
    "SAMPLE_RATELIMIT_ACS",
    "SAMPLE_DATAEXPOSURE_STORY",
    "SAMPLE_DATAEXPOSURE_ACS",
]
