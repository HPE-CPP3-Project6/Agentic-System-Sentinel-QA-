import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys, useRun } from "@/api/hooks";
import { isRunInFlight } from "@/api/runLifecycle";
import type { RunStatus } from "@/api/types";
import { useRunStreamStore } from "@/stores/runStreamStore";

/** Keep WebSocket store and TanStack Query in sync with REST run status. */
export function useRunProgressSync(runId: string | undefined, storyId?: string) {
  const qc = useQueryClient();
  const { data: run } = useRun(runId);
  const { setPhases, setRunStatus, setFailure } = useRunStreamStore();

  useEffect(() => {
    if (!runId || !run) return;

    if (run.phases.length) {
      setPhases(run.phases);
    }

    const status = run.status as RunStatus;
    if (status === "failed") {
      setRunStatus("failed");
      if (run.error_code) {
        setFailure(
          run.error_code,
          run.error_message ?? "Run failed",
          run.current_phase ?? undefined,
        );
      }
    } else {
      setRunStatus(status);
    }

    if (status === "paused" || status === "completed") {
      qc.invalidateQueries({ queryKey: queryKeys.artifact(runId) });
      qc.invalidateQueries({ queryKey: queryKeys.script(runId) });
      if (storyId) {
        qc.invalidateQueries({ queryKey: queryKeys.storyRuns(storyId) });
      }
    }
  }, [run, runId, storyId, setPhases, setRunStatus, setFailure, qc]);

  // Poll REST while in-flight even if WS disconnects.
  useEffect(() => {
    if (!runId || !isRunInFlight(run?.status)) return;
    const id = window.setInterval(() => {
      qc.invalidateQueries({ queryKey: queryKeys.run(runId) });
    }, 1500);
    return () => window.clearInterval(id);
  }, [runId, run?.status, qc]);
}
