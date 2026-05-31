import { lazy, Suspense, useCallback, useEffect, useMemo } from "react";
import { useParams, useSearch } from "wouter";
import { Loader2 } from "lucide-react";
import { useRun, useStory } from "@/api/hooks";
import {
  parseFlowMode,
  parsePipelineMode,
  type FlowMode,
} from "@/api/pipelineSettings";
import {
  isTabAccessible,
  tabForRun,
  unlockedTabsForRun,
} from "@/api/runLifecycle";
import { useRunStream } from "@/api/ws";
import { useAutoAdvanceExecution } from "@/hooks/useAutoAdvanceExecution";
import { useAutoPipelineNavigation } from "@/hooks/useAutoPipelineNavigation";
import { useMockRunStream } from "@/hooks/useMockRunStream";
import { useRunProgressSync } from "@/hooks/useRunProgressSync";
import type { PipelineMode, PhaseName, RunStatus, WorkspaceTab } from "@/api/types";
import { AppShell } from "@/components/AppShell";
import { PipelineStepper } from "@/components/workspace/PipelineStepper";
import { RunHistorySidebar } from "@/components/workspace/RunHistorySidebar";
import { InputTab } from "@/components/workspace/tabs/InputTab";
import { SurfaceMapTab } from "@/components/workspace/tabs/SurfaceMapTab";
import { ScenariosTab } from "@/components/workspace/tabs/ScenariosTab";
import { RunTab } from "@/components/workspace/tabs/RunTab";
import { useUiStore } from "@/stores/uiStore";

const ScriptsTab = lazy(() =>
  import("@/components/workspace/tabs/ScriptsTab").then((m) => ({ default: m.ScriptsTab })),
);
const ReportTab = lazy(() =>
  import("@/components/workspace/tabs/ReportTab").then((m) => ({ default: m.ReportTab })),
);

function TabFallback() {
  return (
    <div className="flex items-center gap-2 p-8 text-muted">
      <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.75} />
      Loading…
    </div>
  );
}

function parseTab(raw: string | null): WorkspaceTab {
  const tabs: WorkspaceTab[] = ["input", "surface", "scenarios", "scripts", "run", "report"];
  return tabs.includes(raw as WorkspaceTab) ? (raw as WorkspaceTab) : "input";
}

export function WorkspacePage() {
  const params = useParams<{ storyId: string }>();
  const storyId = params.storyId ?? "";
  const search = useSearch();
  const { data: story } = useStory(storyId);
  const setActiveRunId = useUiStore((s) => s.setActiveRunId);

  const query = useMemo(() => new URLSearchParams(search), [search]);
  const activeTab = parseTab(query.get("tab"));
  const runId = query.get("run") ?? undefined;
  const flowMode = parseFlowMode(query.get("flow"));
  const pipelineMode = parsePipelineMode(query.get("pmode"));

  const { data: activeRun } = useRun(runId);

  useEffect(() => {
    setActiveRunId(runId ?? null);
    return () => setActiveRunId(null);
  }, [runId, setActiveRunId]);

  const setQuery = useCallback(
    (patch: Record<string, string | undefined>) => {
      const next = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined) next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      window.history.replaceState(null, "", `/workspace/${storyId}${qs ? `?${qs}` : ""}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
    [storyId],
  );

  useRunStream(runId);
  useMockRunStream(runId);
  useRunProgressSync(runId, storyId);

  const setFlowMode = useCallback(
    (mode: FlowMode) => setQuery({ flow: mode }),
    [setQuery],
  );
  const setPipelineMode = useCallback(
    (mode: PipelineMode) => setQuery({ pmode: mode }),
    [setQuery],
  );

  /** Forward navigation after an explicit user action (Generate Tests, Continue, etc.). */
  const goToTab = useCallback((tab: WorkspaceTab) => setQuery({ tab }), [setQuery]);

  useAutoPipelineNavigation(flowMode, runId, activeRun, activeTab, goToTab);
  useAutoAdvanceExecution(flowMode, runId, activeRun);

  const unlockedTabs = useMemo(
    () => unlockedTabsForRun(runId, activeRun?.status, activeRun?.current_phase),
    [runId, activeRun?.status, activeRun?.current_phase],
  );

  const onTabChange = useCallback(
    (tab: WorkspaceTab) => {
      if (!isTabAccessible(tab, runId, activeRun?.status, activeRun?.current_phase)) {
        return;
      }
      setQuery({ tab });
    },
    [setQuery, runId, activeRun?.status, activeRun?.current_phase],
  );

  const onRunStarted = useCallback(
    (id: string) => setQuery({ run: id, tab: "surface" }),
    [setQuery],
  );

  const onSelectRun = useCallback(
    (id: string, status?: RunStatus, currentPhase?: PhaseName | null) => {
      setQuery({ run: id, tab: tabForRun(status, currentPhase) });
    },
    [setQuery],
  );

  // Redirect deep-links to tabs that are not yet reachable for this run.
  useEffect(() => {
    if (!runId || !activeRun) return;
    if (isTabAccessible(activeTab, runId, activeRun.status, activeRun.current_phase)) {
      return;
    }
    const fallback = tabForRun(activeRun.status, activeRun.current_phase);
    if (fallback !== activeTab) {
      setQuery({ tab: fallback });
    }
  }, [activeTab, activeRun, runId, setQuery]);

  const tabAccessible = isTabAccessible(
    activeTab,
    runId,
    activeRun?.status,
    activeRun?.current_phase,
  );

  return (
    <AppShell title={story?.title} showBack activeNav="workspace">
      <PipelineStepper
        activeTab={activeTab}
        onTabChange={onTabChange}
        unlockedTabs={unlockedTabs}
      />
      <div className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-[1fr_240px]">
        <div>
          {activeTab === "input" && (
            <InputTab
              storyId={storyId}
              flowMode={flowMode}
              pipelineMode={pipelineMode}
              onFlowModeChange={setFlowMode}
              onPipelineModeChange={setPipelineMode}
              onRunStarted={onRunStarted}
            />
          )}
          {activeTab === "surface" && tabAccessible && (
            <SurfaceMapTab
              runId={runId}
              flowMode={flowMode}
              onTabChange={() => goToTab("scenarios")}
            />
          )}
          {activeTab === "scenarios" && tabAccessible && (
            <ScenariosTab
              runId={runId}
              flowMode={flowMode}
              onTabChange={() => goToTab("scripts")}
            />
          )}
          {activeTab === "scripts" && tabAccessible && (
            <Suspense fallback={<TabFallback />}>
              <ScriptsTab
                runId={runId}
                flowMode={flowMode}
                onTabChange={() => goToTab("run")}
              />
            </Suspense>
          )}
          {activeTab === "run" && tabAccessible && (
            <RunTab runId={runId} onTabChange={() => goToTab("report")} />
          )}
          {activeTab === "report" && tabAccessible && (
            <Suspense fallback={<TabFallback />}>
              <ReportTab runId={runId} storyTitle={story?.title} />
            </Suspense>
          )}
          {activeTab !== "input" && !tabAccessible && (
            <TabFallback />
          )}
        </div>
        <aside className="hidden lg:block">
          <RunHistorySidebar storyId={storyId} activeRunId={runId} onSelectRun={onSelectRun} />
        </aside>
      </div>
    </AppShell>
  );
}
