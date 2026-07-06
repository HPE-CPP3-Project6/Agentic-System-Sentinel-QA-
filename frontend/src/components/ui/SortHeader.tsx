import { ChevronDown, ChevronsUpDown, ChevronUp } from "lucide-react";
import type { SortState } from "@/lib/useTableSort";
import { cn } from "@/lib/cn";

/** A sortable `<th>`. Renders the column label with a direction indicator and
 *  toggles the sort on click. Sits inside a `.data-table` header row. */
export function SortHeader({
  label,
  sortKey,
  sort,
  onSort,
  className,
  align = "left",
}: {
  label: string;
  sortKey: string;
  sort: SortState | null;
  onSort: (key: string) => void;
  className?: string;
  align?: "left" | "right";
}) {
  const active = sort?.key === sortKey;
  const Icon = !active ? ChevronsUpDown : sort.dir === "asc" ? ChevronUp : ChevronDown;
  return (
    <th
      className={className}
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          // Inherits text-transform/tracking from the parent <th> (uppercase in
          // .data-table contexts; plain in custom tables) so it fits both.
          "inline-flex select-none items-center gap-1 hover:text-foreground",
          align === "right" && "flex-row-reverse",
          active ? "text-foreground" : "text-muted",
        )}
      >
        {label}
        <Icon
          className={cn("h-3 w-3 shrink-0", active ? "opacity-100" : "opacity-40")}
          strokeWidth={2}
          aria-hidden
        />
      </button>
    </th>
  );
}
