import { useMemo } from "react";
import { formatDistanceToNow } from "date-fns";
import { History, RotateCw } from "lucide-react";
import { useStoryRuns } from "@/api/hooks";
import type { PhaseName, RunStatus } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface RunHistorySidebarProps {
  storyId: string;
  activeRunId?: string;
  onSelectRun: (runId: string, status?: RunStatus, currentPhase?: PhaseName | null) => void;
}

export function RunHistorySidebar({
  storyId,
  activeRunId,
  onSelectRun,
}: RunHistorySidebarProps) {
  const { data: runs } = useStoryRuns(storyId);

  const sorted = useMemo(
    () => [...(runs ?? [])].sort((a, b) => b.started_at.localeCompare(a.started_at)),
    [runs],
  );

  return (
    <div className="panel">
      <div className="panel-header flex items-center gap-2">
        <History className="h-3.5 w-3.5" strokeWidth={1.75} />
        Run history
      </div>
      <div className="max-h-[480px] overflow-y-auto">
        {!sorted.length ? (
          <p className="p-3 text-xs text-muted">No runs yet.</p>
        ) : (
          <table className="data-table text-xs">
            <thead>
              <tr>
                <th>Run</th>
                <th>Gate</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((run) => (
                <tr
                  key={run.run_id}
                  className={cn(
                    "cursor-pointer",
                    activeRunId === run.run_id && "bg-surface-elevated",
                  )}
                  onClick={() => onSelectRun(run.run_id, run.status, run.current_phase)}
                >
                  <td>
                    <div className="font-mono">{run.run_id}</div>
                    <div className="text-muted">
                      {formatDistanceToNow(new Date(run.started_at), { addSuffix: true })}
                    </div>
                  </td>
                  <td>
                    <Badge variant={run.run_validity === "OK" ? "success" : "caution"} className="normal-case">
                      {run.suite_quality ?? run.run_validity}
                    </Badge>
                    {run.resilience_pct != null && (
                      <div className="mt-1 text-muted">{run.resilience_pct}%</div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {sorted[0] && (
        <div className="border-t border-border p-2">
          <Button size="sm" variant="outline" className="w-full" onClick={() => onSelectRun(sorted[0].run_id, sorted[0].status, sorted[0].current_phase)}>
            <RotateCw className="h-3.5 w-3.5" strokeWidth={1.75} />
            Open latest report
          </Button>
        </div>
      )}
    </div>
  );
}
