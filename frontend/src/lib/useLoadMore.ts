import { useEffect, useState } from "react";

/**
 * Incremental "load more" windowing for an unbounded list. Shows `step` items
 * initially and reveals `step` more per click. Clamps back down when the list
 * shrinks (e.g. a filter is applied) so the control never claims more than
 * exists.
 */
export function useLoadMore<T>(items: T[], step = 15) {
  const [count, setCount] = useState(step);

  useEffect(() => {
    setCount((c) => Math.min(Math.max(step, c), Math.max(step, items.length)));
  }, [items.length, step]);

  const visible = items.slice(0, count);
  return {
    visible,
    shown: visible.length,
    total: items.length,
    hasMore: count < items.length,
    remaining: Math.max(0, items.length - count),
    showMore: () => setCount((c) => c + step),
    showAll: () => setCount(items.length),
  };
}
