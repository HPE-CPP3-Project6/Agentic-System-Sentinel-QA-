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
  mode?: string,
) {
  useEffect(() => {
    if (flowMode !== "auto" || !runId || !activeRun) return;

    if (activeRun.status === "completed") {
      const next = tabForRun(activeRun.status, activeRun.current_phase, mode);
      // PRE_CODE deliverable is the design report; post-code auto flow lands on Report too.
      if (next === "report" && activeTab !== "report") {
        goToTab("report");
      }
      return;
    }

    if (activeRun.status === "failed") return;

    const next = tabForRun(activeRun.status, activeRun.current_phase, mode);
    if (next !== "input" && next !== activeTab) {
      goToTab(next);
    }
  }, [flowMode, runId, activeRun, activeRun?.status, activeRun?.current_phase, activeTab, goToTab, mode]);
}
