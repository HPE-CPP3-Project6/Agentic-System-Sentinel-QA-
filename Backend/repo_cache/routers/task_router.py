"""
routers/task_router.py
----------------------
Task CRUD endpoints — all routes require a valid JWT (US-C15).

Security guarantees on every endpoint:
    - `get_current_user` dependency rejects requests with missing or invalid tokens.
    - Every DB query filters by `user_id == current_user.id` — users can NEVER
      access or mutate another user's tasks (FR4, US-D15/AC1, AC2, AC3).
    - Soft-delete filters (`deleted_at IS NULL`) are applied globally so deleted
      tasks are invisible (US-D22/AC2, AC4).
    - AuditLog entries are written inside the SAME transaction as the task
      mutation (US-C11, US-D24 — atomicity guarantee).

Endpoints:
    POST   /tasks          – Create a task (+ audit CREATE log)
    GET    /tasks          – Advanced query engine: filter + sort active tasks (Phase 3)
    GET    /tasks/{id}     – Retrieve a single task
    PATCH  /tasks/{id}     – Partially update a task
    DELETE /tasks/{id}     – Soft-delete a task (+ audit DELETE log)

Phase 3 additions (Discovery & Organisation):
    - GET /tasks/ now accepts optional query params:
        priority   : Filter by Low | Medium | High           (US1)
        status     : Filter by Active | Completed            (US2)
        date_filter: Overdue | Today | Upcoming              (US3)
      All active filters are combined with logical AND          (US4)
    - sort_by    : due_date | priority | created_at           (US6/7/8)
    - sort_order : asc | desc                                 (US6/8)
    - Priority sort uses a SQL CASE statement (High=1, Medium=2, Low=3)
      so it follows the strict hierarchy, not alphabetical order (US7).
    - due_date sort uses nullslast() so tasks without a due date always
      sink to the bottom regardless of sort direction (US6).
"""

import uuid
from datetime import datetime, date, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import asc, case, desc, func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import AuditLog, Task, User
from schemas import TaskCreate, TaskOut, PaginatedTaskResponse, TaskResponse, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_owned_task(task_id: str, user: User, db: Session) -> Task:
    """
    Fetch a task that:
        1. Matches `task_id`
        2. Is owned by `user` (US-D15: prevents ID tampering)
        3. Has NOT been soft-deleted

    Raises:
        404 – task not found or not owned by the current user.
              Returning 404 (not 403) avoids confirming that the task exists
              for a different user — an information-leakage mitigation.
    """
    task = (
        db.query(Task)
        .filter(
            Task.id == task_id,
            Task.user_id == user.id,      # SECURITY: strict ownership check
            Task.deleted_at.is_(None),    # Exclude soft-deleted (US-D22/AC2)
        )
        .first()
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found.",   # Generic — do not leak existence info
        )
    return task


def _write_audit_log(
    db: Session,
    user_id: int,
    task_id: str,
    action: str,
) -> None:
    """
    Append an immutable audit log entry to the current session/transaction.

    This function must be called BEFORE `db.commit()` so the log and the
    task mutation are committed atomically (US-C11/AC1, US-D24/AC1).

    Args:
        db      : Active database session.
        user_id : ID of the user performing the action.
        task_id : ID of the affected task.
        action  : "CREATE" or "DELETE".
    """
    log_entry = AuditLog(
        user_id=user_id,
        task_id=task_id,
        action=action,
        # Server-side timestamp — clients cannot manipulate this value
        timestamp=datetime.now(timezone.utc),
    )
    db.add(log_entry)
    # NOTE: do NOT call db.commit() here; let the caller control the transaction


# ---------------------------------------------------------------------------
# POST /tasks  –  Create a task
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=TaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new task",
    description=(
        "Creates a task owned by the authenticated user and atomically logs "
        "the creation in the audit trail (US-C11)."
    ),
)
def create_task(
    task_in: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),   # US-C15: requires valid JWT
) -> Task:
    """
    FR7: Task creation with all required attributes.
    US-C11: Creation audit log written in the same transaction.
    """
    task_id = str(uuid.uuid4())   # UUID prevents sequential ID enumeration

    new_task = Task(
        id=task_id,
        user_id=current_user.id,                # Binds task to authenticated user
        title=task_in.title,
        description=task_in.description,
        priority=task_in.priority.value,
        due_date=task_in.due_date,
        status=task_in.status.value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(new_task)

    # AUDIT (US-C11): log creation in the SAME transaction — if the commit
    # fails, neither the task nor the log entry will be persisted (atomicity).
    _write_audit_log(db, user_id=current_user.id, task_id=task_id, action="CREATE")

    db.commit()
    db.refresh(new_task)
    return new_task


# ---------------------------------------------------------------------------
# GET /tasks/  –  Advanced query engine (Phase 3)
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=PaginatedTaskResponse,
    summary="List, filter & paginate active tasks (Phase 4 — Pagination)",
    description=(
        "Returns a paginated envelope of tasks owned by the authenticated user that "
        "have NOT been soft-deleted. Supports optional filtering by priority, status, "
        "and date range, with configurable sorting. All filters use logical AND (US4). "
        "Priority sort follows High > Medium > Low via SQL CASE (US7). Tasks without a "
        "due date always appear at the bottom (US6). Use `skip` and `limit` to page "
        "through results; `total` in the response holds the full filtered count (NFR4)."
    ),
)
def list_tasks(
    # ── Filters (all optional — omitting a filter returns all values) ───────
    priority: Optional[str] = Query(
        default=None,
        description="Filter by priority: Low | Medium | High (US1)",
    ),
    status: Optional[str] = Query(
        default=None,
        description="Filter by status: Active | Completed (US2)",
    ),
    date_filter: Optional[str] = Query(
        default=None,
        description="Date-based filter: Today | Upcoming | Overdue (US3)",
    ),
    # ── Sorting ─────────────────────────────────────────────────────────────
    sort_by: Optional[str] = Query(
        default="due_date",
        description="Sort field: due_date | priority | created_at (default: due_date)",
    ),
    sort_order: Optional[str] = Query(
        default="asc",
        description="Sort direction: asc | desc (default: asc)",
    ),
    # ── Pagination ───────────────────────────────────────────────────────────
    skip: int = Query(
        default=0,
        ge=0,
        description="Number of records to skip (offset). Must be >= 0.",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
        description="Maximum records to return per page (1–100, default 50).",
    ),
    # ── Dependencies ────────────────────────────────────────────────────────
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedTaskResponse:
    """
    Phase 3 + Phase 4 — Advanced Query Engine with Pagination.

    FR4       : Data isolation — only the current user's tasks are returned.
    US-D22/AC2: Soft-deleted tasks are excluded from all results.
    US1–US4   : Priority / status / date filters combined via logical AND.
    US6       : Due-date sort with NULLs last.
    US7       : Priority sort via CASE (High=1, Medium=2, Low=3) + created_at tiebreak.
    US8       : Creation-timestamp sort.
    NFR4/AC1  : Pagination prevents returning the entire dataset at once;
                a separate COUNT query feeds the `total` field so the client
                can render pagination controls without a second API call.
    """

    # ── 1. Base query: isolation + soft-delete guard ─────────────────────────
    query = db.query(Task).filter(
        Task.user_id == current_user.id,   # SECURITY: strict ownership (FR4)
        Task.deleted_at.is_(None),          # Exclude soft-deleted tasks (US-D22/AC2)
    )

    # ── 2. Apply optional filters (logical AND — US4) ────────────────────────

    # US1: Priority filter — case-insensitive title-case normalisation
    if priority:
        # Normalise to title-case ("high" → "High") so the filter matches DB values
        query = query.filter(Task.priority == priority.strip().title())

    # US2: Status filter
    if status:
        query = query.filter(Task.status == status.strip().title())

    # US3: Date-based filter
    if date_filter:
        # Compute today's date boundaries in UTC so comparisons are timezone-consistent.
        # We use date() from the stored UTC datetime to strip the time component.
        today_utc = datetime.now(timezone.utc).date()
        today_start = datetime(
            today_utc.year, today_utc.month, today_utc.day,
            tzinfo=timezone.utc
        )
        tomorrow_start = today_start + timedelta(days=1)

        normalised_df = date_filter.strip().lower()

        if normalised_df == "today":
            # "Today": due_date falls within the current calendar day (UTC).
            # We cast due_date to a date and compare, which strips time-of-day
            # so any task due at any hour today matches.
            query = query.filter(
                Task.due_date >= today_start,      # on or after midnight today
                Task.due_date < tomorrow_start,    # before midnight tomorrow
            )

        elif normalised_df == "upcoming":
            # "Upcoming": due_date is strictly AFTER today (i.e., tomorrow onward).
            query = query.filter(
                Task.due_date >= tomorrow_start,
            )

        elif normalised_df == "overdue":
            # "Overdue": due_date is strictly BEFORE today AND task is not Completed.
            # A completed task is never considered overdue regardless of its due date.
            query = query.filter(
                Task.due_date < today_start,       # past due
                Task.status != "Completed",        # not already done
            )

    # ── 3. Apply sorting ─────────────────────────────────────────────────────
    normalised_sort = (sort_by or "due_date").strip().lower()
    direction = desc if (sort_order or "asc").strip().lower() == "desc" else asc

    if normalised_sort == "priority":
        # US7: Priority hierarchy sort — High > Medium > Low.
        #
        # SQLAlchemy CASE expression maps each string value to an integer rank:
        #   "High"   → 1  (highest urgency, sorts first under ASC)
        #   "Medium" → 2
        #   "Low"    → 3  (lowest urgency, sorts last under ASC)
        #
        # We use `else_=99` as a safety net for any unexpected priority values
        # so they sink to the bottom rather than causing an error.
        priority_rank = case(
            (Task.priority == "High",   1),
            (Task.priority == "Medium", 2),
            (Task.priority == "Low",    3),
            else_=99,
        )
        # Primary: priority rank;  Secondary: created_at (tiebreak per US7)
        query = query.order_by(
            direction(priority_rank),
            asc(Task.created_at),   # tiebreak — earlier task first within same priority
        )

    elif normalised_sort == "created_at":
        # US8: Sort by creation timestamp.
        query = query.order_by(direction(Task.created_at))

    else:
        # US6: Default — sort by due_date.
        #
        # `nullslast()` ensures tasks without a due_date always appear at the
        # BOTTOM of the result set regardless of sort direction.
        # Without this, NULLs sort first under DESC and last under ASC, which
        # would be inconsistent and confusing for the user.
        if direction is asc:
            query = query.order_by(asc(Task.due_date).nullslast())
        else:
            query = query.order_by(desc(Task.due_date).nullslast())

    # ── 4. COUNT query (NFR4/AC1) ────────────────────────────────────────────
    # Execute a dedicated COUNT against the fully-filtered query BEFORE applying
    # OFFSET / LIMIT. This gives us the total number of matching records so the
    # client can compute page count = ceil(total / limit) — without fetching
    # every row. SQLAlchemy's .count() wraps the filtered query in
    # `SELECT count(*) FROM (subquery)`, sharing the same WHERE clauses but
    # omitting ORDER BY, making it as cheap as possible.
    total: int = query.count()

    # ── 5. Paginated data query ──────────────────────────────────────────────
    # Apply OFFSET and LIMIT AFTER the count so both queries share identical
    # filters. The ORDER BY from step 3 is preserved here — SQLAlchemy carries
    # it through to the final SELECT.
    items: List[Task] = query.offset(skip).limit(limit).all()

    # ── 6. Return the pagination envelope ────────────────────────────────────
    return PaginatedTaskResponse(
        items=items,   # the current page of tasks
        total=total,   # total matching records (pre-pagination)
        skip=skip,     # offset requested by the client
        limit=limit,   # page size requested by the client
    )


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}  –  Retrieve a single task
# ---------------------------------------------------------------------------
@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Retrieve a single task by ID",
    description=(
        "Fetches a task by its UUID. Returns 404 if the task does not exist, "
        "is owned by another user, or has been soft-deleted (US-D15, US-D22/AC2)."
    ),
)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    US-D15: Task ID is validated against user ownership.
    US-D22/AC2: Soft-deleted tasks are not returned.
    """
    return _get_owned_task(task_id, current_user, db)


# ---------------------------------------------------------------------------
# PATCH /tasks/{task_id}  –  Update a task
# ---------------------------------------------------------------------------
@router.patch(
    "/{task_id}",
    response_model=TaskOut,
    summary="Partially update a task",
    description=(
        "Updates one or more fields of an existing task. Only the authenticated "
        "owner can modify a task; attempting to modify another user's task "
        "returns 404 (US-D15)."
    ),
)
def update_task(
    task_id: str,
    task_in: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Task:
    """
    US-D15: Ownership verified before any mutation.
    Only supplied fields are changed (partial update / PATCH semantics).
    """
    task = _get_owned_task(task_id, current_user, db)

    # Apply only the fields that were explicitly provided in the request body
    update_data = task_in.model_dump(exclude_none=True)
    for field, value in update_data.items():
        # Convert enum members to their string values before assignment
        setattr(task, field, value.value if hasattr(value, "value") else value)

    task.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# DELETE /tasks/{task_id}  –  Soft-delete a task
# ---------------------------------------------------------------------------
@router.delete(
    "/{task_id}",
    status_code=status.HTTP_200_OK,
    summary="Soft-delete a task",
    description=(
        "Marks a task as deleted by setting `deleted_at` to the current UTC time. "
        "The task is immediately hidden from all list/search endpoints "
        "(US-D22/AC1, AC2). A background purge job will permanently remove it "
        "after the undo window expires (AC3). The deletion is logged atomically "
        "in the audit trail (US-D24)."
    ),
)
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    US-D22/AC1: Soft-delete by setting deleted_at.
    US-D24: Deletion audit log written in the SAME transaction.
    US-D15/AC1, AC2: Ownership verified; tampered IDs return 404.
    """
    task = _get_owned_task(task_id, current_user, db)

    # SOFT DELETE (US-D22/AC1): mark deleted without physical removal
    task.deleted_at = datetime.now(timezone.utc)

    # AUDIT (US-D24): log deletion atomically — both changes commit together
    _write_audit_log(db, user_id=current_user.id, task_id=task_id, action="DELETE")

    db.commit()

    return {
        "detail": "Task deleted successfully.",
        "task_id": task_id,
        "undo_available_for_minutes": 30,  # FR: undo window hint to client
    }
