import type { ProjectState } from "@/api/types";
import { computeSummary } from "@/lib/reportSummary";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";

/** Execution summary dashboard (req 4): total · passed · failed · success %. */
export function SummaryTile({ artifact }: { artifact: ProjectState }) {
  const s = computeSummary(artifact);
  if (s.total === 0) return null;

  const stats: { label: string; value: string | number; tone?: string }[] = [
    { label: "Total", value: s.total },
    { label: "Passed", value: s.passed, tone: "text-success" },
    { label: "Failed", value: s.failed, tone: s.failed > 0 ? "text-danger" : undefined },
    { label: "Errored", value: s.error, tone: s.error > 0 ? "text-caution" : undefined },
    { label: "Skipped", value: s.skipped, tone: "text-muted" },
    { label: "Success", value: `${s.successPct}%`, tone: "text-primary" },
  ];

  return (
    <Card>
      <CardHeader><CardTitle>Execution summary</CardTitle></CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
          {stats.map((st) => (
            <div key={st.label} className="text-center">
              <p className={cn("text-2xl font-semibold tabular-nums", st.tone)}>{st.value}</p>
              <p className="text-[11px] uppercase tracking-wide text-muted">{st.label}</p>
            </div>
          ))}
        </div>
        {/* pass-rate bar */}
        <div className="mt-4 h-2 w-full overflow-hidden rounded bg-border">
          <div
            className="h-full rounded bg-success transition-all"
            style={{ width: `${s.successPct}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
