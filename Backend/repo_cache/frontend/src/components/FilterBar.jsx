/**
 * src/components/FilterBar.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Unified filter, sort, and search toolbar for the Task Dashboard.
 *
 * Architecture:
 *   · Filter dropdowns (Priority, Status, Date, Sort By, Sort Order) are
 *     controlled by the parent Dashboard — any change is forwarded immediately
 *     via `onChange(key, value)`, which triggers a backend re-fetch.
 *   · Keyword search uses LOCAL state + a 500 ms debounce before calling
 *     `onSearch(value)` to avoid hammering the parent on every keystroke.
 *     Because the backend has no title-search endpoint, the parent applies
 *     this as a client-side filter over the fetched page.
 *   · "Reset" clears both the local search input and all parent filter state
 *     via the `onReset()` callback.
 *
 * Props:
 *   filters   – { priority, status, date_filter, sort_by, sort_order }
 *   search    – current committed search string (controlled by parent)
 *   onChange(key, value) – called when a dropdown changes
 *   onSearch(value)      – called (debounced 500 ms) when search text changes
 *   onReset()            – called when Reset button is clicked
 *   activeCount          – number of active filters (drives badge on Reset btn)
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useState, useEffect, useRef } from 'react'

// ── Shared select style ────────────────────────────────────────────────────────
const SELECT_CLS =
  'bg-slate-800/80 border border-white/10 text-slate-300 text-xs font-medium rounded-xl ' +
  'px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/40 ' +
  'transition-all duration-200 cursor-pointer hover:border-white/20 appearance-none pr-7'

// Wraps a <select> with a caret icon (since appearance-none hides the native one)
function SelectWrapper({ children, className = '' }) {
  return (
    <div className={`relative ${className}`}>
      {children}
      <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500"
           fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="m19.5 8.25-7.5 7.5-7.5-7.5" />
      </svg>
    </div>
  )
}

export default function FilterBar({ filters, search, onChange, onSearch, onReset, activeCount = 0 }) {
  // Local state for the text input — debounced before reaching the parent
  const [localSearch, setLocalSearch] = useState(search)
  const debounceRef = useRef(null)

  // Keep local search in sync if parent resets it externally
  useEffect(() => { setLocalSearch(search) }, [search])

  // 500 ms debounce: emit the search string to the parent only after the user
  // stops typing for half a second, preventing excessive renders/re-fetches.
  function handleSearchChange(e) {
    const value = e.target.value
    setLocalSearch(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => onSearch(value), 500)
  }

  // Cleanup debounce timer if the component unmounts mid-typing
  useEffect(() => () => clearTimeout(debounceRef.current), [])

  function handleReset() {
    setLocalSearch('')
    clearTimeout(debounceRef.current)
    onReset()
  }

  return (
    <div className="bg-white/[0.03] border border-white/8 rounded-2xl p-4 mb-6 space-y-3">

      {/* ── Row 1: Search ────────────────────────────────────────────────── */}
      <div className="relative">
        <svg className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none"
             fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round"
                d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z" />
        </svg>
        <input
          id="filter-search"
          type="text"
          value={localSearch}
          onChange={handleSearchChange}
          placeholder="Search tasks by title… (filtered on current page)"
          className="w-full bg-slate-800/60 border border-white/10 rounded-xl pl-10 pr-4 py-2.5
                     text-sm text-white placeholder-slate-600
                     focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-500/40
                     transition-all duration-200"
        />
        {/* Live debounce indicator */}
        {localSearch && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-slate-600 font-medium">
            500ms
          </span>
        )}
      </div>

      {/* ── Row 2: Filter + Sort dropdowns + Reset ────────────────────────── */}
      <div className="flex flex-wrap gap-2 items-center">

        {/* Priority */}
        <SelectWrapper>
          <select
            id="filter-priority"
            value={filters.priority}
            onChange={(e) => onChange('priority', e.target.value)}
            className={SELECT_CLS}
          >
            <option value="">All Priorities</option>
            <option value="High">🔴 High</option>
            <option value="Medium">🟡 Medium</option>
            <option value="Low">🔵 Low</option>
          </select>
        </SelectWrapper>

        {/* Status */}
        <SelectWrapper>
          <select
            id="filter-status"
            value={filters.status}
            onChange={(e) => onChange('status', e.target.value)}
            className={SELECT_CLS}
          >
            <option value="">All Statuses</option>
            <option value="Active">Active</option>
            <option value="Completed">Completed</option>
          </select>
        </SelectWrapper>

        {/* Date filter */}
        <SelectWrapper>
          <select
            id="filter-date"
            value={filters.date_filter}
            onChange={(e) => onChange('date_filter', e.target.value)}
            className={SELECT_CLS}
          >
            <option value="">All Dates</option>
            <option value="Today">Due Today</option>
            <option value="Upcoming">Upcoming</option>
            <option value="Overdue">Overdue</option>
          </select>
        </SelectWrapper>

        {/* Divider */}
        <div className="h-6 w-px bg-white/10 hidden sm:block" />

        {/* Sort by */}
        <SelectWrapper>
          <select
            id="filter-sort-by"
            value={filters.sort_by}
            onChange={(e) => onChange('sort_by', e.target.value)}
            className={SELECT_CLS}
          >
            <option value="due_date">Sort: Due Date</option>
            <option value="priority">Sort: Priority</option>
            <option value="created_at">Sort: Created</option>
          </select>
        </SelectWrapper>

        {/* Sort order */}
        <SelectWrapper>
          <select
            id="filter-sort-order"
            value={filters.sort_order}
            onChange={(e) => onChange('sort_order', e.target.value)}
            className={SELECT_CLS}
          >
            <option value="asc">↑ Asc</option>
            <option value="desc">↓ Desc</option>
          </select>
        </SelectWrapper>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Reset button — only bold when filters are active */}
        <button
          id="filter-reset"
          onClick={handleReset}
          className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-xl
                      border transition-all duration-200 active:scale-95
                      ${activeCount > 0
                        ? 'bg-indigo-600/20 border-indigo-500/40 text-indigo-300 hover:bg-indigo-600/30'
                        : 'bg-white/5 border-white/10 text-slate-500 hover:text-slate-300 hover:bg-white/10'
                      }`}
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round"
                  d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99" />
          </svg>
          Reset
          {activeCount > 0 && (
            <span className="bg-indigo-500 text-white text-[10px] font-bold w-4 h-4 rounded-full
                             flex items-center justify-center leading-none">
              {activeCount}
            </span>
          )}
        </button>
      </div>
    </div>
  )
}
