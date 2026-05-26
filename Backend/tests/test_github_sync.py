"""Golden tests for github_sync change-type handling (C3) + SHA persistence (C4).

Targets the two regressions:
    C3 — A renamed file (`change_type == "R"`) used to leave stale vectors
         at the old path AND never gain vectors at the new path. Typechanges
         (`"T"`, file ↔ symlink) were ignored entirely.
    C4 — `previous_commit` was reset to None on every daemon restart, so the
         next sync re-embedded the ENTIRE corpus instead of just the diff.

These tests mock GitPython + Chroma rather than spinning a real repo, so they
run in milliseconds and need no network.

Run from Backend/:
    pytest tests/test_github_sync.py -v
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import MagicMock, patch

import pytest


# --------------------------------------------------------------------------- #
# Fixtures: mock GitPython + Chroma so we can construct SovereignSyncService  #
# without ever touching real disk or the network                              #
# --------------------------------------------------------------------------- #


def _make_diff_item(
    change_type: str,
    *,
    a_path: Optional[str] = None,
    b_path: Optional[str] = None,
) -> SimpleNamespace:
    """Mimic gitpython's Diff object: only `.change_type`, `.a_path`, `.b_path` read."""
    return SimpleNamespace(change_type=change_type, a_path=a_path, b_path=b_path)


@pytest.fixture
def service(tmp_path: Path):
    """Build a SovereignSyncService with all GitPython + Chroma I/O mocked.

    `_setup_repository` is patched to a no-op so __init__ doesn't try to
    clone anything. The service's `.repo` is set to a Mock the test fills in.
    """
    from database import github_sync as gh

    cache_dir = tmp_path / "repo"
    chroma_dir = tmp_path / "chroma"
    cache_dir.mkdir()
    chroma_dir.mkdir()

    with patch.object(gh.SovereignSyncService, "_setup_repository", lambda self: None), \
         patch.object(gh, "chromadb") as chromadb_mock, \
         patch.object(gh, "JinaCodeEmbeddingFunction"):
        chromadb_mock.PersistentClient.return_value.get_or_create_collection.return_value = MagicMock()
        svc = gh.SovereignSyncService(
            repo_url="https://example.invalid/repo.git",
            cache_dir=cache_dir,
            chroma_dir=chroma_dir,
            sync_interval=1,
        )
    svc.repo = MagicMock()
    svc.repo.head.commit.hexsha = "newsha" + "0" * 34
    return svc


# --------------------------------------------------------------------------- #
# C3 — rename / typechange handling                                            #
# --------------------------------------------------------------------------- #


def test_rename_deletes_old_path_and_adds_new(service):
    """The headline C3 fix: a Python file renamed must trigger both a delete
    of the old vectors AND an add of the new path. Previously: silent data loss
    (stale vectors orphaned at old path; new path never indexed).
    """
    service.previous_commit = "oldsha" + "0" * 34
    rename = _make_diff_item("R", a_path="src/old_name.py", b_path="src/new_name.py")
    service.repo.commit.return_value.diff.return_value = [rename]

    changed = service._get_changed_files()

    assert "src/old_name.py" in changed["deleted"]
    assert "src/new_name.py" in changed["added"]
    assert changed["modified"] == set()


def test_rename_into_untracked_extension_drops_old_adds_nothing(service):
    """A .py → .md rename: old vectors should die, no new vectors get added
    (because .md is not in TRACKED_SUFFIXES). Loss-tolerant by design.
    """
    service.previous_commit = "oldsha" + "0" * 34
    rename = _make_diff_item("R", a_path="src/foo.py", b_path="docs/foo.md")
    service.repo.commit.return_value.diff.return_value = [rename]

    changed = service._get_changed_files()

    assert changed["deleted"] == {"src/foo.py"}
    assert changed["added"] == set()


def test_typechange_treated_as_modify(service):
    """File ↔ symlink swap at the same path → modify (re-embed)."""
    service.previous_commit = "oldsha" + "0" * 34
    typechange = _make_diff_item("T", a_path="src/lib.py", b_path="src/lib.py")
    service.repo.commit.return_value.diff.return_value = [typechange]

    changed = service._get_changed_files()

    assert changed["modified"] == {"src/lib.py"}
    assert changed["added"] == set()
    assert changed["deleted"] == set()


def test_unknown_change_type_treated_as_modify_not_dropped(service):
    """Future-proofing: an unknown change_type (e.g. git's 'X' / 'B' / 'C')
    should fall back to 'modify' instead of being silently ignored."""
    service.previous_commit = "oldsha" + "0" * 34
    weird = _make_diff_item("X", a_path="src/lib.py", b_path="src/lib.py")
    service.repo.commit.return_value.diff.return_value = [weird]

    changed = service._get_changed_files()

    assert changed["modified"] == {"src/lib.py"}


def test_added_modified_deleted_still_work(service):
    """Sanity: the original A/M/D handling is unbroken by the new R/T branches."""
    service.previous_commit = "oldsha" + "0" * 34
    diffs = [
        _make_diff_item("A", b_path="src/new.py"),
        _make_diff_item("M", a_path="src/changed.py", b_path="src/changed.py"),
        _make_diff_item("D", a_path="src/gone.py"),
    ]
    service.repo.commit.return_value.diff.return_value = diffs

    changed = service._get_changed_files()

    assert changed["added"] == {"src/new.py"}
    assert changed["modified"] == {"src/changed.py"}
    assert changed["deleted"] == {"src/gone.py"}


# --------------------------------------------------------------------------- #
# C4 — SHA persistence across daemon restarts                                  #
# --------------------------------------------------------------------------- #


def test_persist_then_load_round_trip(service):
    """Persist a SHA, read it back, get the same value."""
    sha = "abc123def456" + "0" * 28
    service._persist_last_synced_sha(sha)
    assert service._load_last_synced_sha() == sha


def test_load_returns_none_when_sidecar_missing(service):
    """Cold start (no prior sync) returns None — caller falls back to indexing
    everything, same as before."""
    # Sidecar file does NOT exist
    assert not service._sha_state_file.exists()
    assert service._load_last_synced_sha() is None


def test_load_strips_whitespace(service):
    """The sidecar might be edited by hand or have a trailing newline; tolerate."""
    service._sha_state_file.write_text("   abcdef\n", encoding="utf-8")
    assert service._load_last_synced_sha() == "abcdef"


def test_load_returns_none_when_file_empty(service):
    """An empty sidecar (truncated write) should not pretend to be a valid SHA."""
    service._sha_state_file.write_text("", encoding="utf-8")
    assert service._load_last_synced_sha() is None
