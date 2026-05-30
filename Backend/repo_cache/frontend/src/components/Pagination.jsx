/**
 * src/components/Pagination.jsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Pagination controls bar for the task grid (NFR4).
 *
 * Props:
 *   total          – Total matching records from the backend (pre-pagination).
 *   limit          – Page size (records per page).
 *   skip           – Current offset applied to the query.
 *   onPageChange(newSkip) – Called by Prev / Next buttons; parent updates skip.
 *
 * Derivations (all computed — no extra state needed):
 *   currentPage = floor(skip / limit) + 1
 *   totalPages  = ceil(total / limit)
 *
 * "Previous" is disabled when currentPage === 1.
 * "Next"     is disabled when currentPage === totalPages (or total === 0).
 * ─────────────────────────────────────────────────────────────────────────────
 */

export default function Pagination({ total, limit, skip, onPageChange }) {
  // Guard: nothing to paginate
  if (total === 0) return null

  const currentPage = Math.floor(skip / limit) + 1
  const totalPages  = Math.ceil(total / limit)

  const hasPrev = currentPage > 1
  const hasNext = currentPage < totalPages

  const btnBase =
    'inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium ' +
    'border transition-all duration-200 active:scale-95 '

  const btnActive =
    btnBase +
    'bg-white/5 hover:bg-white/10 border-white/10 text-slate-300 hover:text-white '

  const btnDisabled =
    btnBase +
    'bg-transparent border-white/5 text-slate-700 cursor-not-allowed '

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-3 mt-8
                    pt-5 border-t border-white/8">

      {/* Page info */}
      <p className="text-xs text-slate-500 order-2 sm:order-1">
        Page{' '}
        <span className="text-slate-300 font-semibold">{currentPage}</span>
        {' '}of{' '}
        <span className="text-slate-300 font-semibold">{totalPages}</span>
        <span className="mx-2 text-slate-700">·</span>
        <span className="text-slate-400 font-medium">{total}</span> total task{total !== 1 ? 's' : ''}
      </p>

      {/* Prev / Page chips / Next */}
      <div className="flex items-center gap-2 order-1 sm:order-2">

        {/* Previous */}
        <button
          id="pagination-prev"
          onClick={() => onPageChange(skip - limit)}
          disabled={!hasPrev}
          className={hasPrev ? btnActive : btnDisabled}
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
          </svg>
          Prev
        </button>

        {/* Page number chips — show at most 5 around the current page */}
        <div className="flex items-center gap-1">
          {buildPageRange(currentPage, totalPages).map((page, i) =>
            page === '…' ? (
              <span key={`ellipsis-${i}`} className="px-1 text-slate-600 text-xs select-none">…</span>
            ) : (
              <button
                key={page}
                id={`pagination-page-${page}`}
                onClick={() => onPageChange((page - 1) * limit)}
                className={`w-8 h-8 rounded-lg text-xs font-semibold transition-all duration-150
                            ${page === currentPage
                              ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-900/40'
                              : 'bg-white/5 hover:bg-white/10 text-slate-400 hover:text-white border border-white/10'
                            }`}
              >
                {page}
              </button>
            )
          )}
        </div>

        {/* Next */}
        <button
          id="pagination-next"
          onClick={() => onPageChange(skip + limit)}
          disabled={!hasNext}
          className={hasNext ? btnActive : btnDisabled}
        >
          Next
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// ── Helper: build a compact page range with ellipsis ──────────────────────────
// e.g. totalPages=10, current=5 → [1, '…', 4, 5, 6, '…', 10]
function buildPageRange(current, total) {
  if (total <= 7) {
    // Enough space to show all pages
    return Array.from({ length: total }, (_, i) => i + 1)
  }

  const pages = new Set([1, total, current])
  if (current > 1)     pages.add(current - 1)
  if (current < total) pages.add(current + 1)

  const sorted = [...pages].sort((a, b) => a - b)
  const result = []

  for (let i = 0; i < sorted.length; i++) {
    if (i > 0 && sorted[i] - sorted[i - 1] > 1) result.push('…')
    result.push(sorted[i])
  }

  return result
}
