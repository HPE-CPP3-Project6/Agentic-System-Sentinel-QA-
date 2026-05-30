"""
models.py
---------
SQLAlchemy ORM models for the Smart Task Manager.

Tables:
    users      – Registered application users
    tasks      – Individual task items (supports soft-delete)
    audit_logs – Immutable record of task create/delete events (FR audit logging)

Security notes:
    - Passwords are NEVER stored in plain text (NFR8).  The `hashed_password`
      column stores only bcrypt hashes computed in auth.py.
    - `user_id` foreign keys on tasks and audit_logs enforce data isolation
      at the database layer (FR4, US-D15).
    - `deleted_at` enables soft-delete (US-D22/AC1) without destroying data.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Index,
)
from sqlalchemy.orm import relationship

from database import Base


# ---------------------------------------------------------------------------
# Helper: current UTC time (timezone-aware)
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    """Returns the current UTC timestamp as an aware datetime object."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# User Model
# ---------------------------------------------------------------------------
class User(Base):
    """
    Represents a registered user.

    Columns:
        id              – Auto-incrementing integer primary key.
        email           – Unique, indexed email address used as the login identity.
        hashed_password – bcrypt hash of the user's password (NFR8: no plaintext).
        created_at      – UTC timestamp of account creation.
    """

    __tablename__ = "users"

    id: int = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email: str = Column(String(255), unique=True, index=True, nullable=False)
    # SECURITY: Only bcrypt hashes are stored here — never raw passwords (NFR8)
    hashed_password: str = Column(String(255), nullable=False)
    created_at: datetime = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Relationships (for ORM convenience; not strictly required by API layer)
    tasks = relationship("Task", back_populates="owner", lazy="dynamic")
    audit_logs = relationship("AuditLog", back_populates="user", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r}>"


# ---------------------------------------------------------------------------
# Task Model
# ---------------------------------------------------------------------------
class Task(Base):
    """
    Represents a task item created by a user.

    Soft-delete pattern (US-D22):
        - `deleted_at` is NULL for active tasks.
        - When a user deletes a task, `deleted_at` is set to the current UTC
          time instead of removing the row.
        - The API layer filters out rows where `deleted_at IS NOT NULL` so they
          are invisible to the end user (AC2).
        - A background job (or TTL check) permanently removes them after the
          undo window expires (AC3).
        - All search/filter queries respect this filter (AC4).

    Security (US-D15):
        - `user_id` is a foreign key back to `users.id`.
        - Every query MUST include `filter(Task.user_id == current_user.id)` so
          that a user can never access another user's tasks by guessing task IDs.
    """

    __tablename__ = "tasks"

    # Primary key: UUID string for unpredictability (harder to enumerate/tamper)
    id: str = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        nullable=False,
    )

    # Foreign key — enforces ownership at the DB layer (FR4, US-D15/AC1)
    user_id: int = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,          # Indexed for fast per-user queries
    )

    # Core task attributes (FR7)
    title: str = Column(String(255), nullable=False)
    description: str = Column(String(200), nullable=True)
    priority: str = Column(String(10), default="Medium", nullable=False)
    due_date: datetime = Column(DateTime(timezone=True), nullable=True)
    status: str = Column(String(20), default="Active", nullable=False)

    # Timestamps
    created_at: datetime = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: datetime = Column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    # Soft-delete (US-D22/AC1): NULL = not deleted; timestamp = deleted
    deleted_at: datetime = Column(DateTime(timezone=True), nullable=True, default=None)

    # Composite index: accelerates "give me all active tasks for this user" queries
    __table_args__ = (
        Index("ix_tasks_user_id_deleted_at", "user_id", "deleted_at"),
    )

    owner = relationship("User", back_populates="tasks")

    def __repr__(self) -> str:
        return f"<Task id={self.id!r} title={self.title!r} user_id={self.user_id}>"


# ---------------------------------------------------------------------------
# AuditLog Model
# ---------------------------------------------------------------------------
class AuditLog(Base):
    """
    Immutable audit trail for task creation and deletion events.

    Compliance requirements:
        US-C11 / US-D24: Every CREATE and DELETE action must be logged with
        user_id, task_id, and a timestamp.

    Immutability:
        - No UPDATE or DELETE endpoints exist for this table (AC2/AC4).
        - Application code only ever INSERTs into this table.
        - Database-level immutability can be enforced via a trigger or by
          granting the application role only INSERT privileges on this table.

    Columns:
        id        – Auto-incrementing primary key.
        user_id   – FK to the user who performed the action.
        task_id   – The task that was acted upon (stored as string UUID).
        action    – Either "CREATE" or "DELETE".
        timestamp – UTC time the event occurred.
    """

    __tablename__ = "audit_logs"

    id: int = Column(Integer, primary_key=True, autoincrement=True)

    # FK to users — links the log entry to a specific user (US-C11/AC1)
    user_id: int = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,      # Nullable so logs survive user deletion
        index=True,
    )

    # task_id stored as plain String; the referenced task may be soft-deleted
    task_id: str = Column(String(36), nullable=False, index=True)

    # Action type — constrained to "CREATE" or "DELETE" by the application layer
    action: str = Column(String(10), nullable=False)

    # Timestamp is set server-side, not client-side (prevents tampering)
    timestamp: datetime = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="audit_logs")

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} action={self.action!r} "
            f"task_id={self.task_id!r} user_id={self.user_id}>"
        )
