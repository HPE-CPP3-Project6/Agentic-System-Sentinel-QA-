import { cn } from "@/lib/cn";

export interface Stat {
  label: string;
  value: string | number;
  /** Optional text-colour class for the value (e.g. "text-danger"). */
  tone?: string;
  /** Optional native-title explanation. */
  hint?: string;
}

// Static column classes so Tailwind can see them at build time.
const COLS: Record<number, string> = {
  3: "sm:grid-cols-3",
  4: "sm:grid-cols-4",
  5: "sm:grid-cols-5",
  6: "sm:grid-cols-6",
};

/**
 * A compact KPI row: big tabular numbers over small uppercase labels. The focal
 * element for a screen — generalized from the report's execution-summary tile so
 * Surface Map / Scenarios / Run can each lead with one at-a-glance metric.
 */
export function StatRow({ stats, className }: { stats: Stat[]; className?: string }) {
  const cols = COLS[Math.min(6, Math.max(3, stats.length))] ?? "sm:grid-cols-4";
  return (
    <div className={cn("grid grid-cols-2 gap-3", cols, className)}>
      {stats.map((s) => (
        <div key={s.label} className="text-center" title={s.hint}>
          <p className={cn("text-2xl font-semibold tabular-nums", s.tone)}>{s.value}</p>
          <p className="text-[11px] uppercase tracking-wide text-muted">{s.label}</p>
        </div>
      ))}
    </div>
  );
}
