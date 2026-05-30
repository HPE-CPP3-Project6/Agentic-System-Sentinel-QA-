/**
 * src/components/TaskForm.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Reusable form for creating and editing tasks.
 *
 * Props:
 *   initialData  – Pre-fill values when editing (optional; omit for create).
 *   onSubmit(data) – Called with the validated form payload.
 *   onCancel()     – Called when the user dismisses the form.
 *   isLoading      – Shows spinner on the submit button (controlled by parent).
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useState } from 'react'

// Format an ISO datetime string to the YYYY-MM-DD value a <input type="date"> expects
function toDateInputValue(isoString) {
  if (!isoString) return ''
  return isoString.slice(0, 10)
}

// Today's date in YYYY-MM-DD format — used as the min attribute for due_date
function todayString() {
  return new Date().toISOString().slice(0, 10)
}

export default function TaskForm({ initialData = {}, onSubmit, onCancel, isLoading = false }) {
  const [title,       setTitle]       = useState(initialData.title       ?? '')
  const [description, setDescription] = useState(initialData.description ?? '')
  const [priority,    setPriority]    = useState(initialData.priority     ?? 'Medium')
  const [dueDate,     setDueDate]     = useState(toDateInputValue(initialData.due_date))
  const [error,       setError]       = useState('')

  const isEditing = Boolean(initialData.id)

  function handleSubmit(e) {
    e.preventDefault()
    setError('')

    if (!title.trim()) {
      setError('Title is required.')
      return
    }

    // Build the payload — only include optional fields if they have a value
    const payload = {
      title:    title.trim(),
      priority,
    }
    if (description.trim()) payload.description = description.trim()
    // Convert local date string to a UTC ISO datetime the backend accepts
    if (dueDate) payload.due_date = new Date(`${dueDate}T12:00:00Z`).toISOString()

    onSubmit(payload)
  }

  // ── Shared input class ─────────────────────────────────────────────────────
  const inputCls =
    'w-full bg-slate-800/60 border border-white/10 rounded-xl px-4 py-2.5 text-white placeholder-slate-500 text-sm ' +
    'focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/50 transition-all duration-200'

  return (
    <form onSubmit={handleSubmit} noValidate className="space-y-4">

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-2.5">
          <svg className="w-4 h-4 text-red-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-5a.75.75 0 01.75.75v4.5a.75.75 0 01-1.5 0v-4.5A.75.75 0 0110 5zm0 10a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd"/>
          </svg>
          <p className="text-red-300 text-sm">{error}</p>
        </div>
      )}

      {/* Title */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
          Title <span className="text-red-400">*</span>
        </label>
        <input
          id="task-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="What needs to be done?"
          maxLength={255}
          className={inputCls}
        />
      </div>

      {/* Description */}
      <div>
        <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
          Description
        </label>
        <textarea
          id="task-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Add more detail… (optional, max 200 chars)"
          maxLength={200}
          rows={3}
          className={`${inputCls} resize-none`}
        />
        <p className="mt-1 text-right text-xs text-slate-600">{description.length}/200</p>
      </div>

      {/* Priority + Due Date — side by side */}
      <div className="grid grid-cols-2 gap-3">

        {/* Priority */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
            Priority
          </label>
          <select
            id="task-priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
            className={`${inputCls} cursor-pointer`}
          >
            <option value="High">🔴 High</option>
            <option value="Medium">🟡 Medium</option>
            <option value="Low">🔵 Low</option>
          </select>
        </div>

        {/* Due Date */}
        <div>
          <label className="block text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
            Due Date
          </label>
          <input
            id="task-due-date"
            type="date"
            value={dueDate}
            min={todayString()}
            onChange={(e) => setDueDate(e.target.value)}
            className={`${inputCls} [color-scheme:dark]`}
          />
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-3 pt-1">
        <button
          type="button"
          onClick={onCancel}
          className="flex-1 bg-white/5 hover:bg-white/10 border border-white/10 text-slate-300 hover:text-white
                     font-medium rounded-xl px-4 py-2.5 text-sm transition-all duration-200 active:scale-[0.97]"
        >
          Cancel
        </button>
        <button
          id="task-form-submit"
          type="submit"
          disabled={isLoading}
          className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 disabled:cursor-not-allowed
                     text-white font-semibold rounded-xl px-4 py-2.5 text-sm
                     transition-all duration-200 active:scale-[0.98] flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
              </svg>
              Saving…
            </>
          ) : isEditing ? 'Save changes' : 'Create task'}
        </button>
      </div>
    </form>
  )
}
