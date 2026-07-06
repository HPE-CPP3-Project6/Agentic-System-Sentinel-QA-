import { useMemo } from "react";
import { formatDistanceToNow } from "date-fns";
import { History, RotateCw } from "lucide-react";
import { useStoryRuns } from "@/api/hooks";
import type { PhaseName, RunStatus } from "@/api/types";
import { RunDuration } from "@/components/RunDuration";
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
                <th>Duration</th>
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
                    <RunDuration run={run} className="text-muted" />
                  </td>
                  <td>
                    <div className="flex flex-wrap items-center gap-1">
                      <Badge variant={run.run_validity === "OK" ? "success" : "caution"} className="normal-case">
                        {run.suite_quality ?? run.run_validity}
                      </Badge>
                      {run.pipeline_mode && (
                        <Badge variant="muted" className="font-mono text-[10px] normal-case">
                          {String(run.pipeline_mode).startsWith("PRE") ? "PRE" : "POST"}
                        </Badge>
                      )}
                    </div>
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
          <Button
            size="sm"
            variant="outline"
            className="w-full"
            onClick={() => {
              const latest = sorted[0];
              onSelectRun(
                latest.run_id,
                latest.status,
                latest.current_phase,
              );
            }}
            disabled={sorted[0].status !== "completed"}
            title={
              sorted[0].status === "completed"
                ? "Open the latest finished run in Report"
                : "Available when the latest run has completed"
            }
          >
            <RotateCw className="h-3.5 w-3.5" strokeWidth={1.75} />
            Open latest report
          </Button>
        </div>
      )}
    </div>
  );
}
