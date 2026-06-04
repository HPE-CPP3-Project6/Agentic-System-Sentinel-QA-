import { useEffect, useRef } from "react";
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
  // Track whether this run was ever in-flight during the current session.
  // Prevents historical completed runs from ejecting the user to the Report tab
  // when they open a workspace that already shows a finished run.
  const wasInFlight = useRef(false);

  useEffect(() => {
    if (!runId) {
      wasInFlight.current = false;
      return;
    }
    if (activeRun?.status === "running" || activeRun?.status === "queued") {
      wasInFlight.current = true;
    }
  }, [runId, activeRun?.status]);

  useEffect(() => {
    if (flowMode !== "auto" || !runId || !activeRun) return;

    if (activeRun.status === "completed") {
      if (!wasInFlight.current) return;
      const next = tabForRun(activeRun.status, activeRun.current_phase, mode);
      if (next === "report" && activeTab !== "report") {
        goToTab("report");
      }
      return;
    }

    if (activeRun.status === "failed") {
      if (!wasInFlight.current) return;
      const failedTab = tabForRun(activeRun.status, activeRun.current_phase, mode);
      if (failedTab !== "input" && failedTab !== activeTab) {
        goToTab(failedTab);
      }
      return;
    }

    const next = tabForRun(activeRun.status, activeRun.current_phase, mode);
    if (next !== "input" && next !== activeTab) {
      goToTab(next);
    }
  }, [flowMode, runId, activeRun, activeRun?.status, activeRun?.current_phase, activeTab, goToTab, mode]);
}
