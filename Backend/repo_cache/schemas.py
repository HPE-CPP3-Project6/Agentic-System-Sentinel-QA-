"""
schemas.py
----------
Pydantic v2 schemas used for request validation and response serialization.

Design principles:
    - Input schemas (UserCreate, TaskCreate) are strict about what they accept.
    - Output schemas (UserOut, TaskOut) use `from_attributes=True` so SQLAlchemy
      model instances can be serialized directly.
    - Passwords are NEVER included in any response schema (NFR8).
    - Enum types enforce the closed set of valid values for priority and status,
      providing a first layer of validation before data reaches the database.

Phase 2 additions:
    - Past due-date validation on TaskCreate / TaskUpdate (Task Editing US2/AC2).
    - Whitespace stripping on `title` (US-C2/AC1).
    - HTML tag stripping on `description` to prevent injection (US-C7/AC1).
    - `TaskResponse` – richer response schema with explicit `task_id` field.
    - `TaskFullUpdate` – full-replace schema used by PUT /tasks/{id}.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations – enforce closed value sets
# ---------------------------------------------------------------------------
class PriorityEnum(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"


class StatusEnum(str, Enum):
    active = "Active"
    completed = "Completed"


class ActionEnum(str, Enum):
    create = "CREATE"
    delete = "DELETE"


# ===========================================================================
# USER SCHEMAS
# ===========================================================================

class UserCreate(BaseModel):
    """
    Payload accepted by POST /register.

    Validation:
        - `email` is validated as a proper email address by Pydantic's EmailStr.
        - `password` must be at least 8 characters; the raw value is discarded
          immediately after hashing in the auth layer (NFR8).
    """

    email: EmailStr
    password: str = Field(
        ...,
        min_length=8,
        description="Plain-text password — hashed before storage (NFR8).",
    )

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        """
        Enforce a minimum complexity policy:
          - At least one uppercase letter
          - At least one digit
        Adjust rules as needed for your security policy.
        """
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        return v


class UserOut(BaseModel):
    """
    User data returned by the API. Password hash is intentionally excluded (NFR8).
    """

    id: int
    email: EmailStr
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================================
# TOKEN SCHEMAS
# ===========================================================================

class Token(BaseModel):
    """JWT access token returned by POST /login."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Parsed claims extracted from a verified JWT."""

    user_id: Optional[int] = None


# ===========================================================================
# TASK SCHEMAS
# ===========================================================================

# ---------------------------------------------------------------------------
# Shared sanitization helpers
# ---------------------------------------------------------------------------

def _strip_html(value: Optional[str]) -> Optional[str]:
    """
    Remove HTML tags and decode HTML entities from a string.
    Prevents stored-XSS / injection via description fields (US-C7/AC1).
    """
    if value is None:
        return value
    # Remove any HTML tags (e.g. <script>, <b>, etc.)
    clean = re.sub(r"<[^>]+>", "", value)
    # Decode remaining HTML entities (e.g. &lt; → <) so they display correctly
    return html.unescape(clean).strip()


def _reject_past_date(due_date: Optional[datetime]) -> Optional[datetime]:
    """
    Raise a ValueError if the supplied due_date is in the past.
    Timezone-naive datetimes are assumed to be UTC (Task Editing US2/AC2).
    """
    if due_date is None:
        return due_date
    # Normalise to UTC-aware for a fair comparison
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)
    if due_date < datetime.now(timezone.utc):
        raise ValueError("due_date cannot be in the past.")
    return due_date


# ===========================================================================
# TASK SCHEMAS  (Phase 2 – enhanced validation)
# ===========================================================================

class TaskCreate(BaseModel):
    """
    Payload accepted by POST /tasks.

    Validation (Phase 2 additions):
        - `title` is stripped of leading/trailing whitespace and must not be
          empty after stripping (US-C2/AC1).
        - `description` is HTML-sanitized (US-C7/AC1) and capped at 200 chars.
        - `due_date` must not be in the past (Task Editing US2/AC2).
        - `priority` defaults to Medium (US-C3/AC1); `status` defaults to
          Active (US-C3/AC2).  Both are enum-constrained (US-C2/AC2).
    """

    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Task title — mandatory, whitespace-stripped (US-C2/AC1).",
    )
    description: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional task description, max 200 chars, HTML-stripped (US-C7/AC1).",
    )
    priority: PriorityEnum = Field(
        default=PriorityEnum.medium,
        description="Task priority — defaults to Medium (US-C3/AC1).",
    )
    due_date: Optional[datetime] = Field(
        default=None,
        description="Optional due date (ISO 8601). Must not be in the past.",
    )
    status: StatusEnum = Field(
        default=StatusEnum.active,
        description="Task status — defaults to Active (US-C3/AC2).",
    )

    # ── Field-level validators ──────────────────────────────────────────────

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: str) -> str:
        """Strip whitespace; reject blank titles after stripping (US-C2/AC1)."""
        stripped = v.strip() if isinstance(v, str) else v
        if not stripped:
            raise ValueError("title must not be blank or whitespace-only.")
        return stripped

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, v: Optional[str]) -> Optional[str]:
        """HTML-strip the description to prevent injection (US-C7/AC1)."""
        return _strip_html(v)

    @field_validator("due_date", mode="after")
    @classmethod
    def validate_due_date(cls, v: Optional[datetime]) -> Optional[datetime]:
        """Reject past due dates (Task Editing US2/AC2)."""
        return _reject_past_date(v)


class TaskUpdate(BaseModel):
    """
    Payload accepted by PATCH /tasks/{task_id}  (partial update — all optional).
    Applies the same validation rules as TaskCreate.
    """

    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=200)
    priority: Optional[PriorityEnum] = None
    due_date: Optional[datetime] = None
    status: Optional[StatusEnum] = None

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        stripped = v.strip()
        if not stripped:
            raise ValueError("title must not be blank or whitespace-only.")
        return stripped

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, v: Optional[str]) -> Optional[str]:
        return _strip_html(v)

    @field_validator("due_date", mode="after")
    @classmethod
    def validate_due_date(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _reject_past_date(v)


class TaskFullUpdate(BaseModel):
    """
    Payload accepted by PUT /tasks/{task_id}  (full replacement — all required
    except description and due_date which remain optional by design).
    Used by the Phase 2 PUT endpoint.
    """

    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=200)
    priority: PriorityEnum = Field(default=PriorityEnum.medium)
    due_date: Optional[datetime] = None
    status: StatusEnum = Field(default=StatusEnum.active)

    @field_validator("title", mode="before")
    @classmethod
    def strip_title(cls, v: str) -> str:
        stripped = v.strip() if isinstance(v, str) else v
        if not stripped:
            raise ValueError("title must not be blank or whitespace-only.")
        return stripped

    @field_validator("description", mode="before")
    @classmethod
    def sanitize_description(cls, v: Optional[str]) -> Optional[str]:
        return _strip_html(v)

    @field_validator("due_date", mode="after")
    @classmethod
    def validate_due_date(cls, v: Optional[datetime]) -> Optional[datetime]:
        return _reject_past_date(v)


class TaskOut(BaseModel):
    """
    Task data returned by the API.  `deleted_at` is excluded from public
    responses — soft-deleted tasks are invisible to the client (US-D22/AC2).
    """

    id: str
    user_id: int
    title: str
    description: Optional[str]
    priority: str
    due_date: Optional[datetime]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskResponse(TaskOut):
    """
    Phase 2 enriched response schema.
    Inherits all fields from TaskOut and surfaces `task_id` as an explicit
    top-level field for frontend convenience.  `deleted_at` is never exposed.
    """

    # Alias the `id` field as `task_id` at the serialization layer so clients
    # don't have to know the internal primary-key name.
    task_id: str = Field(alias="id", serialization_alias="task_id")

    model_config = {"from_attributes": True, "populate_by_name": True}


# ===========================================================================
# PAGINATION SCHEMAS  (Phase 4)
# ===========================================================================

class PaginatedTaskResponse(BaseModel):
    """
    Envelope returned by GET /tasks/ (Phase 4 \u2014 NFR4 Performance).

    Wraps the paginated result set with metadata needed for the client to
    render pagination controls and know how many total records exist without
    fetching the entire dataset.

    Fields:
        items  \u2013 The actual page of Task records (max `limit` items).
        total  \u2013 Total number of tasks matching the current filters
                  (BEFORE pagination). Used by the client to compute page
                  count: ceil(total / limit).
        skip   \u2013 Number of records skipped (i.e., the offset applied).
        limit  \u2013 Maximum records requested for this page.

    Design note:
        `total` is computed with a dedicated COUNT query that shares the same
        WHERE clauses as the data query but skips ORDER BY / OFFSET / LIMIT,
        making it as fast as possible (NFR4/AC1).
    """

    items: List[TaskResponse]
    total: int = Field(..., description="Total matching records (pre-pagination).")
    skip: int  = Field(..., description="Number of records skipped (offset).")
    limit: int = Field(..., description="Maximum records returned in this page.")

    model_config = {"from_attributes": True}


# `from __future__ import annotations` at the top of this module defers ALL
# annotation evaluation (PEP 563). Pydantic v2 therefore cannot resolve
# `List[TaskResponse]` inside PaginatedTaskResponse at class-definition time.
# Calling model_rebuild() after the full module is parsed forces Pydantic to
# re-evaluate every annotation now that all names are in scope.
PaginatedTaskResponse.model_rebuild()


# ===========================================================================
# AUDIT LOG SCHEMAS
# ===========================================================================

class AuditLogOut(BaseModel):
    """Read-only view of a single audit log entry (admin/debugging use)."""

    id: int
    user_id: Optional[int]
    task_id: str
    action: str
    timestamp: datetime

    model_config = {"from_attributes": True}
