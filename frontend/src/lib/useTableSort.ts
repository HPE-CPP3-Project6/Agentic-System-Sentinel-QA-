import { useMemo, useState } from "react";

export type SortDir = "asc" | "desc";
export interface SortState {
  key: string;
  dir: SortDir;
}

/** Column key → value getter. Return null/undefined for "no value" (sorts last). */
export type Accessors<T> = Record<string, (row: T) => string | number | null | undefined>;

function compare(a: unknown, b: unknown, dir: SortDir): number {
  const an = a === null || a === undefined || a === "";
  const bn = b === null || b === undefined || b === "";
  if (an && bn) return 0;
  if (an) return 1; // empty values always sort last, regardless of direction
  if (bn) return -1;
  let r: number;
  if (typeof a === "number" && typeof b === "number") r = a - b;
  else r = String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  return dir === "asc" ? r : -r;
}

/**
 * Client-side column sorting for a table. Pass a STABLE `accessors` object
 * (module-level const or useMemo) so the sort doesn't recompute every render.
 * Clicking a header cycles asc → desc → unsorted.
 */
export function useTableSort<T>(
  rows: T[],
  accessors: Accessors<T>,
  initial: SortState | null = null,
) {
  const [sort, setSort] = useState<SortState | null>(initial);

  const sorted = useMemo(() => {
    if (!sort || !accessors[sort.key]) return rows;
    const get = accessors[sort.key];
    return [...rows].sort((a, b) => compare(get(a), get(b), sort.dir));
  }, [rows, sort, accessors]);

  function onSort(key: string) {
    setSort((s) => {
      if (!s || s.key !== key) return { key, dir: "asc" };
      if (s.dir === "asc") return { key, dir: "desc" };
      return null; // third click clears the sort
    });
  }

  return { sorted, sort, onSort };
}
