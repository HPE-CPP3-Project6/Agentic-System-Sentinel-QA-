"""
purge_deleted_tasks.py
----------------------
Background maintenance script — permanently removes tasks that have been
soft-deleted beyond the configured undo window (US-D22/AC3).

Run this script as a scheduled job (e.g., Windows Task Scheduler, cron):
    python purge_deleted_tasks.py

Or integrate it into a Celery/APScheduler background worker.
"""

from datetime import datetime, timedelta, timezone

from database import SessionLocal
from config import settings
from models import Task


def purge_expired_soft_deletes() -> int:
    """
    Permanently DELETE rows from the `tasks` table where:
        - `deleted_at` is NOT NULL (task was soft-deleted)
        - `deleted_at` is older than SOFT_DELETE_UNDO_WINDOW_MINUTES

    Returns the number of rows permanently deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=settings.SOFT_DELETE_UNDO_WINDOW_MINUTES
    )

    db = SessionLocal()
    try:
        expired_tasks = (
            db.query(Task)
            .filter(
                Task.deleted_at.isnot(None),
                Task.deleted_at <= cutoff,
            )
            .all()
        )

        count = len(expired_tasks)
        for task in expired_tasks:
            db.delete(task)

        db.commit()
        print(f"[purge] Permanently deleted {count} expired soft-deleted task(s).")
        return count
    except Exception as exc:
        db.rollback()
        print(f"[purge] Error during purge: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    purge_expired_soft_deletes()
