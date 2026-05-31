import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { queryKeys, useRun } from "@/api/hooks";
import type { RunStatus } from "@/api/types";
import { useRunStreamStore } from "@/stores/runStreamStore";

/**
 * Reconcile the WebSocket store with REST run status. The live channel is the
 * WebSocket (useRunStream); this hook layers REST reconciliation on top so the
 * stepper/status stay correct if the socket drops or misses an event.
 *
 * Polling itself lives in `useRun` (refetchInterval 1.5s while in-flight) —
 * we intentionally do NOT add a second interval here. A previous version ran
 * its own 1.5s setInterval on top of useRun's, double-polling /api/runs and
 * competing with the now-working WS stream.
 */
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
}
