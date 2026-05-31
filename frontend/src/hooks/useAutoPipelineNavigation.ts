import { useEffect } from "react";
import { tabForRun } from "@/api/runLifecycle";
import type { FlowMode } from "@/api/pipelineSettings";
import type { RunSummary, WorkspaceTab } from "@/api/types";

/** In auto flow, follow the run across pipeline tabs as backend phases advance. */
export function useAutoPipelineNavigation(
  flowMode: FlowMode,
  runId: string | undefined,
  activeRun: RunSummary | undefined,
  activeTab: WorkspaceTab,
  goToTab: (tab: WorkspaceTab) => void,
) {
  useEffect(() => {
    if (flowMode !== "auto" || !runId || !activeRun) return;
    // After the run ends, let the user browse earlier stages freely.
    if (activeRun.status === "completed" || activeRun.status === "failed") return;
    const next = tabForRun(activeRun.status, activeRun.current_phase);
    if (next !== "input" && next !== activeTab) {
      goToTab(next);
    }
  }, [flowMode, runId, activeRun, activeRun?.status, activeRun?.current_phase, activeTab, goToTab]);
}
