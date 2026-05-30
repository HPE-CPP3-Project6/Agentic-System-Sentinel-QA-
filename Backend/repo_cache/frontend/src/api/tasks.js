/**
 * src/api/tasks.js
 * ─────────────────────────────────────────────────────────────────────────────
 * Task-related API helpers.  All functions use the shared Axios instance from
 * axios.js which automatically attaches the JWT Authorization header.
 *
 * Backend contract:
 *   GET    /tasks/           → PaginatedTaskResponse { items, total, skip, limit }
 *   POST   /tasks/           → TaskOut (newly created task)
 *   PATCH  /tasks/{task_id}  → TaskOut (partial update)
 *   DELETE /tasks/{task_id}  → { detail, task_id, undo_available_for_minutes }
 * ─────────────────────────────────────────────────────────────────────────────
 */

import api from './axios'

// ── GET /tasks/ ───────────────────────────────────────────────────────────────
//
// Accepts a single params object covering ALL query dimensions:
//   skip        – pagination offset
//   limit       – page size
//   priority    – "Low" | "Medium" | "High"
//   status      – "Active" | "Completed"
//   date_filter – "Today" | "Upcoming" | "Overdue"
//   sort_by     – "due_date" | "priority" | "created_at"
//   sort_order  – "asc" | "desc"
//
// Only non-empty / non-null values are forwarded so the backend treats omitted
// params as "no filter" rather than receiving an empty string it may reject.
export async function getTasks({
  skip        = 0,
  limit       = 9,
  priority    = '',
  status      = '',
  date_filter = '',
  sort_by     = 'due_date',
  sort_order  = 'asc',
} = {}) {
  // Build params object — conditionally include optional filters
  const params = { skip, limit, sort_by, sort_order }
  if (priority)    params.priority    = priority
  if (status)      params.status      = status
  if (date_filter) params.date_filter = date_filter

  return api.get('/tasks/', { params })
}

// ── POST /tasks/ ──────────────────────────────────────────────────────────────
// `taskData` shape: { title, description?, priority, due_date? }
export async function createTask(taskData) {
  return api.post('/tasks/', taskData)
}

// ── PATCH /tasks/{task_id} ────────────────────────────────────────────────────
// Partial update — only send the fields you want to change.
export async function updateTask(taskId, taskData) {
  return api.patch(`/tasks/${taskId}`, taskData)
}

// ── DELETE /tasks/{task_id} ───────────────────────────────────────────────────
// Triggers a soft-delete on the backend (sets deleted_at).
export async function deleteTask(taskId) {
  return api.delete(`/tasks/${taskId}`)
}
