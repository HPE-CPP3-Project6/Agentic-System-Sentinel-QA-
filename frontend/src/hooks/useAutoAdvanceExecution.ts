import { useEffect, useRef } from "react";
import { useAdvanceRun } from "@/api/hooks";
import { canStartExecution } from "@/api/runLifecycle";
import type { FlowMode } from "@/api/pipelineSettings";
import type { RunSummary } from "@/api/types";

/** In auto flow, start executor when the run pauses after compiler (regular-style gate). */
export function useAutoAdvanceExecution(
  flowMode: FlowMode,
  runId: string | undefined,
  activeRun: RunSummary | undefined,
) {
  const advance = useAdvanceRun(runId);
  const startedRef = useRef<string | null>(null);

  useEffect(() => {
    if (flowMode !== "auto" || !runId || !activeRun) return;
    if (!canStartExecution(activeRun.status, activeRun.current_phase)) return;
    if (startedRef.current === runId) return;
    startedRef.current = runId;
    void advance.mutateAsync({ stop_after: null });
  }, [flowMode, runId, activeRun, activeRun?.status, activeRun?.current_phase, advance]);
}
