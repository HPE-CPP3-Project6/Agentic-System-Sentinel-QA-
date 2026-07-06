from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = BACKEND_ROOT / "shim_data" / "sentinel.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StoryRow:
    id: str
    title: str
    body: str
    acceptance_criteria: list[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "acceptance_criteria": self.acceptance_criteria,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class RunRow:
    run_id: str
    story_id: str
    status: str
    mode: str
    stop_after: str | None
    resume_from: str | None
    current_phase: str | None
    started_at: str
    finished_at: str | None
    workspace_dir: str
    artifact_path: str | None
    suite_quality: str | None
    run_validity: str | None
    resilience_pct: float | None
    error_code: str | None
    error_message: str | None
    # Full artifact JSON persisted on completion. The workspace artifact.json
    # is gitignored and dies with the folder; this DB copy makes completed
    # runs' reports survive a re-clone.
    artifact_json: str | None = None

    def to_history_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "pipeline_mode": self.mode,
            "status": self.status,
            "current_phase": self.current_phase,
            "run_validity": self.run_validity or "OK",
            "suite_quality": self.suite_quality,
            "resilience_pct": self.resilience_pct,
        }


class Store:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        # timeout: worker thread writes while API threads read — without a
        # busy timeout, concurrent access raises "database is locked".
        # WAL: readers don't block the writer (and vice versa).
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS stories (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    story_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    stop_after TEXT,
                    resume_from TEXT,
                    current_phase TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    workspace_dir TEXT NOT NULL,
                    artifact_path TEXT,
                    suite_quality TEXT,
                    run_validity TEXT,
                    resilience_pct REAL,
                    error_code TEXT,
                    error_message TEXT,
                    artifact_json TEXT,
                    FOREIGN KEY (story_id) REFERENCES stories(id)
                );
                """
            )
            # Migration for DBs created before artifact_json existed —
            # CREATE TABLE IF NOT EXISTS won't add columns to an existing table.
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
            if "artifact_json" not in cols:
                conn.execute("ALTER TABLE runs ADD COLUMN artifact_json TEXT")

    def create_story(
        self, title: str, body: str, acceptance_criteria: list[str]
    ) -> StoryRow:
        now = _utc_now()
        story_id = f"story-{uuid.uuid4().hex[:12]}"
        row = StoryRow(
            id=story_id,
            title=title,
            body=body,
            acceptance_criteria=acceptance_criteria,
            created_at=now,
            updated_at=now,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO stories (id, title, body, acceptance_criteria, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    row.title,
                    row.body,
                    json.dumps(row.acceptance_criteria),
                    row.created_at,
                    row.updated_at,
                ),
            )
        return row

    def list_stories(self) -> list[StoryRow]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM stories ORDER BY created_at DESC").fetchall()
        return [self._story_from_row(r) for r in rows]

    def get_story(self, story_id: str) -> StoryRow | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM stories WHERE id = ?", (story_id,)).fetchone()
        return self._story_from_row(row) if row else None

    def update_story(
        self,
        story_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        acceptance_criteria: list[str] | None = None,
    ) -> StoryRow | None:
        story = self.get_story(story_id)
        if not story:
            return None
        if title is not None:
            story.title = title
        if body is not None:
            story.body = body
        if acceptance_criteria is not None:
            story.acceptance_criteria = acceptance_criteria
        story.updated_at = _utc_now()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE stories SET title=?, body=?, acceptance_criteria=?, updated_at=?
                WHERE id=?
                """,
                (
                    story.title,
                    story.body,
                    json.dumps(story.acceptance_criteria),
                    story.updated_at,
                    story_id,
                ),
            )
        return story

    def delete_story(self, story_id: str) -> bool:
        if not self.get_story(story_id):
            return False
        for run in self.list_runs_for_story(story_id):
            ws = Path(run.workspace_dir)
            if ws.is_dir():
                shutil.rmtree(ws, ignore_errors=True)
        with self._conn() as conn:
            conn.execute("DELETE FROM runs WHERE story_id=?", (story_id,))
            conn.execute("DELETE FROM stories WHERE id=?", (story_id,))
        return True

    def delete_run(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        if not run:
            return False
        ws = Path(run.workspace_dir)
        if ws.is_dir():
            shutil.rmtree(ws, ignore_errors=True)
        with self._conn() as conn:
            conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        return True

    def story_has_active_run(self, story_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM runs
                WHERE story_id=? AND status IN ('queued', 'running', 'paused')
                LIMIT 1
                """,
                (story_id,),
            ).fetchone()
        return row is not None

    def create_run(
        self,
        story_id: str,
        mode: str,
        stop_after: str | None,
        resume_from: str | None = None,
    ) -> RunRow:
        run_id = f"r_{uuid.uuid4().hex[:8]}"
        workspace = BACKEND_ROOT / "workspace" / "runs" / run_id
        workspace.mkdir(parents=True, exist_ok=True)
        row = RunRow(
            run_id=run_id,
            story_id=story_id,
            status="queued",
            mode=mode,
            stop_after=stop_after,
            resume_from=resume_from,
            current_phase=None,
            started_at=_utc_now(),
            finished_at=None,
            workspace_dir=str(workspace),
            artifact_path=None,
            suite_quality=None,
            run_validity=None,
            resilience_pct=None,
            error_code=None,
            error_message=None,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    run_id, story_id, status, mode, stop_after, resume_from,
                    current_phase, started_at, workspace_dir
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.run_id,
                    row.story_id,
                    row.status,
                    row.mode,
                    row.stop_after,
                    row.resume_from,
                    row.current_phase,
                    row.started_at,
                    row.workspace_dir,
                ),
            )
        return row

    def get_run(self, run_id: str) -> RunRow | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return self._run_from_row(row) if row else None

    def list_runs_for_story(self, story_id: str) -> list[RunRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM runs WHERE story_id=? ORDER BY started_at DESC",
                (story_id,),
            ).fetchall()
        return [self._run_from_row(r) for r in rows]

    # Column names are interpolated into SQL — values are parameterized but
    # identifiers cannot be. This allowlist ensures a future caller wiring a
    # request field into **fields cannot inject SQL via the key.
    _RUN_COLUMNS = frozenset({
        "status", "mode", "stop_after", "resume_from", "current_phase",
        "started_at", "finished_at", "workspace_dir", "artifact_path",
        "suite_quality", "run_validity", "resilience_pct",
        "error_code", "error_message", "artifact_json",
    })

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - self._RUN_COLUMNS
        if unknown:
            raise ValueError(f"update_run: unknown columns {sorted(unknown)}")
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [run_id]
        with self._conn() as conn:
            conn.execute(f"UPDATE runs SET {cols} WHERE run_id=?", vals)

    @staticmethod
    def _story_from_row(row: sqlite3.Row) -> StoryRow:
        return StoryRow(
            id=row["id"],
            title=row["title"],
            body=row["body"],
            acceptance_criteria=json.loads(row["acceptance_criteria"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRow:
        return RunRow(
            run_id=row["run_id"],
            story_id=row["story_id"],
            status=row["status"],
            mode=row["mode"],
            stop_after=row["stop_after"],
            resume_from=row["resume_from"],
            current_phase=row["current_phase"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            workspace_dir=row["workspace_dir"],
            artifact_path=row["artifact_path"],
            suite_quality=row["suite_quality"],
            run_validity=row["run_validity"],
            resilience_pct=row["resilience_pct"],
            error_code=row["error_code"],
            error_message=row["error_message"],
            artifact_json=row["artifact_json"] if "artifact_json" in row.keys() else None,
        )
