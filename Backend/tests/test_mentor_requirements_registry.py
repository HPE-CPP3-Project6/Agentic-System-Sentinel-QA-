"""Registry tests for mentor requirement story catalog."""

from __future__ import annotations

from samples import SAMPLE_STORIES
from samples.mentor_requirements import (
    FUNCTIONAL_KEYS,
    MENTOR_REQUIREMENT_STORIES,
    NFR_KEYS,
)


def test_mentor_registry_has_nineteen_stories() -> None:
    assert len(MENTOR_REQUIREMENT_STORIES) == 19
    assert len(FUNCTIONAL_KEYS) == 11
    assert len(NFR_KEYS) == 8


def test_mentor_stories_merged_into_sample_stories() -> None:
    for key in MENTOR_REQUIREMENT_STORIES:
        assert key in SAMPLE_STORIES
        entry = SAMPLE_STORIES[key]
        assert entry["story"]
        assert entry["acs"]
        assert entry["story_id"].startswith("REQ-")


def test_mentor_story_ids_unique() -> None:
    ids = [s["story_id"] for s in MENTOR_REQUIREMENT_STORIES.values()]
    assert len(ids) == len(set(ids))
