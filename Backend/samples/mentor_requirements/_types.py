"""Shared types for mentor requirement story modules."""

from __future__ import annotations

from typing import List, TypedDict


class MentorStory(TypedDict):
    story: str
    acs: List[str]
    title: str
    story_id: str
    module: str
