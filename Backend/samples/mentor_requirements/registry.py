"""Registry of mentor requirement stories — one pipeline story per FR/NFR section."""

from __future__ import annotations

from typing import Dict, List, Tuple

from samples.mentor_requirements._types import MentorStory
from samples.mentor_requirements.fr_filtering import STORY_ENTRY as FR_FILTERING
from samples.mentor_requirements.fr_persistence import STORY_ENTRY as FR_PERSISTENCE
from samples.mentor_requirements.fr_search import STORY_ENTRY as FR_SEARCH
from samples.mentor_requirements.fr_sorting import STORY_ENTRY as FR_SORTING
from samples.mentor_requirements.fr_task_completion import STORY_ENTRY as FR_TASK_COMPLETION
from samples.mentor_requirements.fr_task_creation import STORY_ENTRY as FR_TASK_CREATION
from samples.mentor_requirements.fr_task_deletion import STORY_ENTRY as FR_TASK_DELETION
from samples.mentor_requirements.fr_task_editing import STORY_ENTRY as FR_TASK_EDITING
from samples.mentor_requirements.fr_task_validation import STORY_ENTRY as FR_TASK_VALIDATION
from samples.mentor_requirements.fr_task_viewing import STORY_ENTRY as FR_TASK_VIEWING
from samples.mentor_requirements.fr_user_management import STORY_ENTRY as FR_USER_MANAGEMENT
from samples.mentor_requirements.nfr_compatibility import STORY_ENTRY as NFR_COMPATIBILITY
from samples.mentor_requirements.nfr_constraints import STORY_ENTRY as NFR_CONSTRAINTS
from samples.mentor_requirements.nfr_maintainability import STORY_ENTRY as NFR_MAINTAINABILITY
from samples.mentor_requirements.nfr_performance import STORY_ENTRY as NFR_PERFORMANCE
from samples.mentor_requirements.nfr_portability import STORY_ENTRY as NFR_PORTABILITY
from samples.mentor_requirements.nfr_reliability import STORY_ENTRY as NFR_RELIABILITY
from samples.mentor_requirements.nfr_security import STORY_ENTRY as NFR_SECURITY
from samples.mentor_requirements.nfr_usability import STORY_ENTRY as NFR_USABILITY

# CLI keys → story payloads (merged into SAMPLE_STORIES by sample_stories.py)
MENTOR_REQUIREMENT_STORIES: Dict[str, MentorStory] = {
    # Functional (FR §1.1–1.11)
    "req-fr-user-mgmt": FR_USER_MANAGEMENT,
    "req-fr-task-create": FR_TASK_CREATION,
    "req-fr-task-validate": FR_TASK_VALIDATION,
    "req-fr-task-view": FR_TASK_VIEWING,
    "req-fr-task-edit": FR_TASK_EDITING,
    "req-fr-task-complete": FR_TASK_COMPLETION,
    "req-fr-task-delete": FR_TASK_DELETION,
    "req-fr-filter": FR_FILTERING,
    "req-fr-sort": FR_SORTING,
    "req-fr-search": FR_SEARCH,
    "req-fr-persist": FR_PERSISTENCE,
    # Non-functional (NFR §2.1–2.8)
    "req-nfr-usability": NFR_USABILITY,
    "req-nfr-performance": NFR_PERFORMANCE,
    "req-nfr-reliability": NFR_RELIABILITY,
    "req-nfr-security": NFR_SECURITY,
    "req-nfr-maintainability": NFR_MAINTAINABILITY,
    "req-nfr-portability": NFR_PORTABILITY,
    "req-nfr-compatibility": NFR_COMPATIBILITY,
    "req-nfr-constraints": NFR_CONSTRAINTS,
}

# Ordered catalog for docs / batch runners
MENTOR_STORY_CATALOG: List[Tuple[str, str, str]] = [
    (key, MENTOR_REQUIREMENT_STORIES[key]["story_id"], MENTOR_REQUIREMENT_STORIES[key]["title"])
    for key in MENTOR_REQUIREMENT_STORIES
]

FUNCTIONAL_KEYS: List[str] = [k for k in MENTOR_REQUIREMENT_STORIES if k.startswith("req-fr-")]
NFR_KEYS: List[str] = [k for k in MENTOR_REQUIREMENT_STORIES if k.startswith("req-nfr-")]
