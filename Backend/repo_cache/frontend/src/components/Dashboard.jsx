/**
 * src/components/Dashboard.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Phase 4 – Stage 3: Advanced Discovery Dashboard.
 *
 * Added in Stage 3 (on top of Stage 2):
 *   · Filter state: priority, status, date_filter, sort_by, sort_order.
 *   · Pagination state: skip (offset) + ITEMS_PER_PAGE (limit).
 *   · useEffect now depends on filters + skip, so any change re-fetches.
 *   · FilterBar component rendered above the task grid.
 *   · Pagination component rendered below the task grid.
 *   · Client-side title search (backend has no search endpoint) filters the
 *     fetched page in-memory after debounce; a banner notifies the user.
 *
 * Unchanged from Stage 2:
 *   · Undo delete toast (US-D19 — 5 second countdown).
 *   · Optimistic status toggle.
 *   · Create / Edit modal with TaskForm.
 *   · Loading skeleton, empty state, error state.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth }    from '../context/AuthContext'
import { getTasks, createTask, updateTask, deleteTask } from '../api/tasks'
import TaskCard   from './TaskCard'
import TaskForm   from './TaskForm'
import FilterBar  from './FilterBar'
import Pagination from './Pagination'

// ── Constants ──────────────────────────────────────────────────────────────────
const UNDO_DURATION_MS = 5000   // US-D19 / AC2 — 5 second undo window
const ITEMS_PER_PAGE   = 9     // 3 × 3 grid per page; smaller than 50 so pagination is testable

// ── Default filter/sort values ─────────────────────────────────────────────────
const DEFAULT_FILTERS = {
  priority:    '',
  status:      '',
  date_filter: '',
  sort_by:     'due_date',
  sort_order:  'asc',
}

export default function Dashboard() {
  const { user, logout } = useAuth()

  // ── Server-driven state ────────────────────────────────────────────────────
  const [tasks,      setTasks]      = useState([])
  const [totalTasks, setTotalTasks] = useState(0)
  const [isLoading,  setIsLoading]  = useState(true)
  const [fetchError, setFetchError] = useState('')

  // ── Filter / sort / pagination state (all drive re-fetches via useEffect) ──
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [skip,    setSkip]    = useState(0)           // pagination offset

  // ── Client-side search (debounced in FilterBar; applied here in-memory) ────
  // The backend has no title-search param, so we filter the fetched page locally.
  const [search, setSearch] = useState('')

  // ── Modal state ────────────────────────────────────────────────────────────
  const [showModal,   setShowModal]   = useState(false)
  const [editingTask, setEditingTask] = useState(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formError,   setFormError]   = useState('')

  // ── Undo toast state (US-D19) ──────────────────────────────────────────────
  const [pendingDelete,   setPendingDelete]   = useState(null)
  const [undoSecondsLeft, setUndoSecondsLeft] = useState(UNDO_DURATION_MS / 1000)
  const undoIntervalRef = useRef(null)
  const undoTimeoutRef  = useRef(null)

  // ── Fetch tasks ────────────────────────────────────────────────────────────
  // Re-runs whenever filters or skip changes (search is client-side, no re-fetch).
  const fetchTasks = useCallback(async () => {
    setIsLoading(true)
    setFetchError('')
    try {
      const response = await getTasks({
        skip,
        limit: ITEMS_PER_PAGE,
        ...filters,   // spreads priority, status, date_filter, sort_by, sort_order
      })
      /*
       * CRITICAL: Backend returns a paginated envelope.
       * response.data = { items: [...tasks], total: N, skip, limit }
       * We must read .items — assigning response.data directly would set tasks
       * to the object itself instead of the array.
       */
      setTasks(response.data.items)
      setTotalTasks(response.data.total)
    } catch (err) {
      setFetchError('Failed to load tasks. Please refresh.')
      console.error('[Dashboard] fetchTasks error:', err)
    } finally {
      setIsLoading(false)
    }
  }, [filters, skip])   // ← re-fetch whenever filters or page changes

  useEffect(() => { fetchTasks() }, [fetchTasks])

  // ── FilterBar handlers ─────────────────────────────────────────────────────
  // Changing a filter resets to page 1 so the user doesn't land on an
  // out-of-range page after narrowing results.
  function handleFilterChange(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }))
    setSkip(0)   // reset to first page on filter change
  }

  function handleReset() {
    setFilters(DEFAULT_FILTERS)
    setSearch('')
    setSkip(0)
  }

  // ── Pagination handler ─────────────────────────────────────────────────────
  function handlePageChange(newSkip) {
    setSkip(newSkip)
    // Scroll to top of task grid on page change for UX
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  // ── Client-side search filter ──────────────────────────────────────────────
  // Applied over the already-fetched page — no extra API call needed.
  const searchedTasks = search.trim()
    ? tasks.filter((t) => t.title.toLowerCase().includes(search.toLowerCase().trim()))
    : tasks

  // Count how many filters are active (to drive the Reset badge in FilterBar)
  const activeFilterCount = [
    filters.priority,
    filters.status,
    filters.date_filter,
    filters.sort_by    !== DEFAULT_FILTERS.sort_by    ? filters.sort_by    : '',
    filters.sort_order !== DEFAULT_FILTERS.sort_order ? filters.sort_order : '',
    search,
  ].filter(Boolean).length

  // ── Modal helpers ──────────────────────────────────────────────────────────
  function openCreateModal() { setEditingTask(null); setFormError(''); setShowModal(true) }
  function openEditModal(task) { setEditingTask(task); setFormError(''); setShowModal(true) }
  function closeModal() { setShowModal(false); setEditingTask(null); setFormError('') }

  // ── Create / Edit ──────────────────────────────────────────────────────────
  async function handleFormSubmit(payload) {
    setFormLoading(true)
    setFormError('')
    try {
      if (editingTask) {
        const { data: updated } = await updateTask(editingTask.id, payload)
        setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)))
      } else {
        await createTask(payload)
        // Refetch first page so the new task appears in the correct sorted position
        setSkip(0)
        if (skip === 0) fetchTasks()   // skip is already 0 — force a refetch
      }
      closeModal()
    } catch (err) {
      const detail = err?.response?.data?.detail
      setFormError(
        Array.isArray(detail)        ? detail[0]?.msg
          : typeof detail === 'string' ? detail
          : 'Something went wrong. Please try again.'
      )
    } finally {
      setFormLoading(false)
    }
  }

  // ── Toggle status ──────────────────────────────────────────────────────────
  async function handleToggleStatus(task) {
    const newStatus = task.status === 'Completed' ? 'Active' : 'Completed'
    setTasks((prev) => prev.map((t) => t.id === task.id ? { ...t, status: newStatus } : t))
    try {
      await updateTask(task.id, { status: newStatus })
    } catch {
      setTasks((prev) => prev.map((t) => t.id === task.id ? { ...t, status: task.status } : t))
    }
  }

  // ── Delete with 5-second undo (US-D19) ────────────────────────────────────
  function handleDeleteRequest(taskId) {
    if (pendingDelete) commitDelete(pendingDelete.taskId)

    const snapshot = tasks.find((t) => t.id === taskId)
    if (!snapshot) return

    setTasks((prev) => prev.filter((t) => t.id !== taskId))
    setTotalTasks((n) => n - 1)

    let seconds = UNDO_DURATION_MS / 1000
    setUndoSecondsLeft(seconds)
    if (undoIntervalRef.current) clearInterval(undoIntervalRef.current)
    undoIntervalRef.current = setInterval(() => {
      seconds -= 1
      setUndoSecondsLeft(seconds)
      if (seconds <= 0) clearInterval(undoIntervalRef.current)
    }, 1000)

    if (undoTimeoutRef.current) clearTimeout(undoTimeoutRef.current)
    const timer = setTimeout(() => commitDelete(taskId), UNDO_DURATION_MS)
    setPendingDelete({ taskId, snapshot, timer })
  }

  function commitDelete(taskId) {
    clearInterval(undoIntervalRef.current)
    clearTimeout(undoTimeoutRef.current)
    setPendingDelete(null)
    deleteTask(taskId).catch((err) => console.error('[Dashboard] deleteTask error:', err))
  }

  function handleUndo() {
    if (!pendingDelete) return
    clearTimeout(pendingDelete.timer)
    clearInterval(undoIntervalRef.current)
    setTasks((prev) => [pendingDelete.snapshot, ...prev])
    setTotalTasks((n) => n + 1)
    setPendingDelete(null)
  }

  // ── Derived counts ─────────────────────────────────────────────────────────
  const activeCount    = tasks.filter((t) => t.status === 'Active').length
  const completedCount = tasks.filter((t) => t.status === 'Completed').length

  // ───────────────────────────────────────────────────────────────────────────
  // Render
  // ───────────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900">

      {/* ── Sticky nav ──────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 bg-slate-900/80 backdrop-blur-xl border-b border-white/5 px-4 sm:px-6">
        <div className="max-w-5xl mx-auto flex items-center justify-between h-16">

          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-indigo-500/20 border border-indigo-500/30 flex items-center justify-center">
              <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
              </svg>
            </div>
            <span className="font-bold text-white text-sm hidden sm:inline">Smart Task Manager</span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-slate-500 text-xs hidden sm:inline">{user?.email}</span>
            <button
              id="header-logout"
              onClick={logout}
              className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white
                         bg-white/5 hover:bg-white/10 border border-white/10
                         px-3 py-1.5 rounded-lg transition-all duration-200"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M8.25 9V5.25A2.25 2.25 0 0 1 10.5 3h6a2.25 2.25 0 0 1 2.25 2.25v13.5A2.25 2.25 0 0 1 16.5 21h-6a2.25 2.25 0 0 1-2.25-2.25V15m-3 0-3-3m0 0 3-3m-3 3H15" />
              </svg>
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">

        {/* Page heading + Add Task */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">My Tasks</h1>
            <p className="text-slate-500 text-sm mt-0.5">
              {isLoading
                ? 'Loading…'
                : totalTasks === 0
                  ? 'No tasks yet — create your first one!'
                  : `${activeCount} active · ${completedCount} completed · ${totalTasks} total`}
            </p>
          </div>

          <button
            id="add-task-btn"
            onClick={openCreateModal}
            className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500
                       text-white font-semibold rounded-xl px-5 py-2.5 text-sm
                       transition-all duration-200 active:scale-[0.97] shadow-lg shadow-indigo-900/40"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add Task
          </button>
        </div>

        {/* ── FilterBar (Stage 3) ───────────────────────────────────────── */}
        <FilterBar
          filters={filters}
          search={search}
          onChange={handleFilterChange}
          onSearch={(val) => { setSearch(val); setSkip(0) }}
          onReset={handleReset}
          activeCount={activeFilterCount}
        />

        {/* Search-active notice — reminds user search is page-scoped */}
        {search.trim() && !isLoading && (
          <div className="mb-4 flex items-center gap-2 text-xs text-amber-400/80
                          bg-amber-400/5 border border-amber-400/20 rounded-xl px-4 py-2.5">
            <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round"
                    d="M11.25 11.25l.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
            </svg>
            Showing <strong className="font-semibold text-amber-300">{searchedTasks.length}</strong> of{' '}
            <strong className="font-semibold text-amber-300">{tasks.length}</strong> tasks on this page
            matching &ldquo;<span className="italic">{search}</span>&rdquo;
          </div>
        )}

        {/* ── Loading skeleton ──────────────────────────────────────────── */}
        {isLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: ITEMS_PER_PAGE }).map((_, i) => (
              <div key={i} className="bg-white/5 border border-white/10 rounded-2xl p-5 animate-pulse space-y-3">
                <div className="h-4 w-20 bg-white/10 rounded-full" />
                <div className="h-4 w-4/5 bg-white/10 rounded" />
                <div className="h-3 w-3/5 bg-white/10 rounded" />
              </div>
            ))}
          </div>
        )}

        {/* ── Fetch error ───────────────────────────────────────────────── */}
        {!isLoading && fetchError && (
          <div className="flex flex-col items-center gap-4 py-20 text-center">
            <div className="w-14 h-14 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
              <svg className="w-7 h-7 text-rose-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126z" />
              </svg>
            </div>
            <p className="text-slate-400 text-sm">{fetchError}</p>
            <button
              onClick={fetchTasks}
              className="bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 text-sm px-4 py-2 rounded-xl"
            >
              Try again
            </button>
          </div>
        )}

        {/* ── Empty state ───────────────────────────────────────────────── */}
        {!isLoading && !fetchError && searchedTasks.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-24 text-center">
            <div className="w-20 h-20 rounded-3xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center">
              <svg className="w-10 h-10 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25Z" />
              </svg>
            </div>
            <div>
              <h2 className="text-white font-semibold mb-1">
                {activeFilterCount > 0 || search ? 'No matching tasks' : 'No tasks yet'}
              </h2>
              <p className="text-slate-500 text-sm">
                {activeFilterCount > 0 || search
                  ? 'Try adjusting your filters or search term.'
                  : 'Click "Add Task" to get started.'}
              </p>
            </div>
            {activeFilterCount > 0 || search ? (
              <button
                onClick={handleReset}
                className="inline-flex items-center gap-2 bg-white/5 hover:bg-white/10 border border-white/10
                           text-slate-300 font-medium rounded-xl px-5 py-2.5 text-sm transition-all"
              >
                Clear all filters
              </button>
            ) : (
              <button
                onClick={openCreateModal}
                className="inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500
                           text-white font-semibold rounded-xl px-5 py-2.5 text-sm transition-all"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                </svg>
                Create your first task
              </button>
            )}
          </div>
        )}

        {/* ── Task grid ─────────────────────────────────────────────────── */}
        {!isLoading && !fetchError && searchedTasks.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {searchedTasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onEdit={openEditModal}
                onDelete={handleDeleteRequest}
                onToggle={handleToggleStatus}
              />
            ))}
          </div>
        )}

        {/* ── Pagination (Stage 3) ──────────────────────────────────────── */}
        {!isLoading && !fetchError && !search.trim() && (
          <Pagination
            total={totalTasks}
            limit={ITEMS_PER_PAGE}
            skip={skip}
            onPageChange={handlePageChange}
          />
        )}

        {/*
         * Note: Pagination is hidden while a client-side search is active
         * because the "total" from the server doesn't reflect the filtered count.
         * The user can clear the search to restore pagination.
         */}
        {!isLoading && search.trim() && searchedTasks.length > 0 && (
          <p className="mt-4 text-center text-xs text-slate-700">
            Pagination is paused during search — clear the search box to browse all pages.
          </p>
        )}
      </main>

      {/* ── Create / Edit modal ────────────────────────────────────────── */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) closeModal() }}
        >
          <div className="w-full max-w-md bg-slate-900 border border-white/10 rounded-2xl shadow-2xl
                          animate-[fadeScaleIn_0.2s_ease-out]">

            <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b border-white/10">
              <h2 className="text-white font-bold text-lg">
                {editingTask ? 'Edit task' : 'New task'}
              </h2>
              <button
                onClick={closeModal}
                className="text-slate-500 hover:text-white p-1.5 rounded-lg hover:bg-white/5 transition-all"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {formError && (
              <div className="mx-6 mt-4 flex items-center gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
                <svg className="w-4 h-4 text-red-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd"
                        d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z"
                        clipRule="evenodd" />
                </svg>
                <p className="text-red-300 text-sm">{formError}</p>
              </div>
            )}

            <div className="p-6">
              <TaskForm
                initialData={editingTask ?? {}}
                onSubmit={handleFormSubmit}
                onCancel={closeModal}
                isLoading={formLoading}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Undo delete toast (US-D19) ──────────────────────────────────── */}
      {pendingDelete && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50
                        flex items-center gap-4 bg-slate-800 border border-white/10 rounded-2xl
                        px-5 py-3.5 shadow-2xl shadow-black/50 animate-[slideUp_0.25s_ease-out]">

          <div className="relative w-8 h-8 shrink-0">
            <svg className="w-8 h-8 -rotate-90" viewBox="0 0 32 32">
              <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor"
                      className="text-white/10" strokeWidth="3"/>
              <circle cx="16" cy="16" r="13" fill="none" stroke="currentColor"
                      className="text-indigo-400 transition-all duration-1000"
                      strokeWidth="3"
                      strokeDasharray={`${2 * Math.PI * 13}`}
                      strokeDashoffset={`${2 * Math.PI * 13 * (1 - undoSecondsLeft / (UNDO_DURATION_MS / 1000))}`}
                      strokeLinecap="round"/>
            </svg>
            <span className="absolute inset-0 flex items-center justify-center text-[10px] font-bold text-indigo-300">
              {undoSecondsLeft}
            </span>
          </div>

          <p className="text-slate-300 text-sm font-medium">Task deleted</p>

          <button
            id="undo-delete-btn"
            onClick={handleUndo}
            className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold
                       px-3 py-1.5 rounded-lg transition-all duration-150 active:scale-95"
          >
            Undo
          </button>
        </div>
      )}

      <style>{`
        @keyframes fadeScaleIn {
          from { opacity: 0; transform: scale(0.95); }
          to   { opacity: 1; transform: scale(1); }
        }
        @keyframes slideUp {
          from { opacity: 0; transform: translate(-50%, 1rem); }
          to   { opacity: 1; transform: translate(-50%, 0); }
        }
      `}</style>
    </div>
  )
}
