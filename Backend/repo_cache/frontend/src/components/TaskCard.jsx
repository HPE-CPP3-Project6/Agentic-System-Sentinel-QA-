/**
 * src/components/TaskCard.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Renders a single task item.
 *
 * US 12 — Visual Status Differentiation (AC1):
 *   When task.status === 'Completed' the card title gets `line-through` and
 *   the card drops to `opacity-50` so it visually recedes from active tasks.
 *
 * US 13 — Priority Color Coding (AC1):
 *   High   → Red  (rose-500)
 *   Medium → Amber (amber-400)
 *   Low    → Blue/Slate (sky-400)
 *
 * Props:
 *   task        – Task object from the API
 *   onEdit(task)        – Parent opens edit form pre-filled with this task
 *   onDelete(taskId)    – Parent handles delete + undo toast
 *   onToggle(task)      – Parent flips status Active ↔ Completed
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ── Priority badge config (US 13) ─────────────────────────────────────────────
const PRIORITY_CONFIG = {
  High:   { dot: 'bg-rose-500',  badge: 'bg-rose-500/15  text-rose-400  border-rose-500/30',  label: 'High'   },
  Medium: { dot: 'bg-amber-400', badge: 'bg-amber-400/15 text-amber-400 border-amber-400/30', label: 'Medium' },
  Low:    { dot: 'bg-sky-400',   badge: 'bg-sky-400/15   text-sky-400   border-sky-400/30',   label: 'Low'    },
}

// Format ISO date string → "Apr 18, 2026"
function formatDate(iso) {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// Is the due date overdue?
function isOverdue(iso, status) {
  if (!iso || status === 'Completed') return false
  return new Date(iso) < new Date()
}

export default function TaskCard({ task, onEdit, onDelete, onToggle }) {
  const isCompleted = task.status === 'Completed'
  const priority    = PRIORITY_CONFIG[task.priority] ?? PRIORITY_CONFIG.Medium
  const overdue     = isOverdue(task.due_date, task.status)
  const dueLabel    = formatDate(task.due_date)

  return (
    /*
     * US 12 / AC1 — opacity + line-through applied to the entire card when completed.
     * Using `transition-all` so toggling feels smooth.
     */
    <div
      className={`group relative bg-white/5 hover:bg-white/[0.07] backdrop-blur-sm border border-white/10
                  rounded-2xl p-5 flex flex-col gap-3 transition-all duration-300
                  ${isCompleted ? 'opacity-50' : 'opacity-100'}`}
    >
      {/* ── Top row: priority badge + action buttons ──────────────────────── */}
      <div className="flex items-center justify-between gap-2">

        {/* Priority badge (US 13 / AC1) */}
        <span className={`inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1
                          rounded-full border ${priority.badge}`}>
          <span className={`w-1.5 h-1.5 rounded-full ${priority.dot}`} />
          {priority.label}
        </span>

        {/* Action buttons — visible on hover */}
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">

          {/* Toggle status */}
          <button
            id={`toggle-${task.id}`}
            onClick={() => onToggle(task)}
            title={isCompleted ? 'Mark as Active' : 'Mark as Completed'}
            className="p-1.5 rounded-lg text-slate-400 hover:text-emerald-400 hover:bg-emerald-400/10
                       transition-all duration-150"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              {isCompleted
                ? <path strokeLinecap="round" strokeLinejoin="round" d="M9 15 3 9m0 0 6-6M3 9h12a6 6 0 0 1 0 12h-3" />
                : <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              }
            </svg>
          </button>

          {/* Edit */}
          <button
            id={`edit-${task.id}`}
            onClick={() => onEdit(task)}
            title="Edit task"
            className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-400 hover:bg-indigo-400/10
                       transition-all duration-150"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Z" />
            </svg>
          </button>

          {/* Delete */}
          <button
            id={`delete-${task.id}`}
            onClick={() => onDelete(task.id)}
            title="Delete task"
            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-400/10
                       transition-all duration-150"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
            </svg>
          </button>
        </div>
      </div>

      {/* ── Title (US 12 / AC1 — line-through when completed) ─────────────── */}
      <h3 className={`text-sm font-semibold text-white leading-snug break-words
                      ${isCompleted ? 'line-through text-slate-400' : ''}`}>
        {task.title}
      </h3>

      {/* ── Description ──────────────────────────────────────────────────────── */}
      {task.description && (
        <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">
          {task.description}
        </p>
      )}

      {/* ── Footer: due date + status chip ───────────────────────────────────── */}
      <div className="flex items-center justify-between mt-auto pt-1">
        {dueLabel ? (
          <span className={`flex items-center gap-1 text-xs font-medium
                            ${overdue ? 'text-rose-400' : 'text-slate-500'}`}>
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5" />
            </svg>
            {overdue ? `Overdue · ${dueLabel}` : dueLabel}
          </span>
        ) : (
          <span className="text-xs text-slate-700">No due date</span>
        )}

        {/* Status chip */}
        <span className={`text-xs font-semibold px-2 py-0.5 rounded-full
                          ${isCompleted
                            ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                            : 'bg-slate-700/60   text-slate-400   border border-white/10'}`}>
          {task.status}
        </span>
      </div>
    </div>
  )
}
