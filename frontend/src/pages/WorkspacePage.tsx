import { lazy, Suspense, useCallback, useEffect, useMemo } from "react";
import { useParams, useSearch } from "wouter";
import { Loader2 } from "lucide-react";
import { useStory } from "@/api/hooks";
import type { WorkspaceTab } from "@/api/types";
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

  useEffect(() => {
    setActiveRunId(runId ?? null);
    return () => setActiveRunId(null);
  }, [runId, setActiveRunId]);

  const setQuery = useCallback(
    (patch: Record<string, string | undefined>) => {
      const next = new URLSearchParams(search);
      for (const [k, v] of Object.entries(patch)) {
        if (v === undefined) next.delete(k);
        else next.set(k, v);
      }
      const qs = next.toString();
      window.history.replaceState(null, "", `/workspace/${storyId}${qs ? `?${qs}` : ""}`);
      window.dispatchEvent(new PopStateEvent("popstate"));
    },
    [search, storyId],
  );

  const onTabChange = useCallback((tab: WorkspaceTab) => setQuery({ tab }), [setQuery]);
  const onRunStarted = useCallback((id: string) => setQuery({ run: id, tab: "surface" }), [setQuery]);
  const onSelectRun = useCallback((id: string) => setQuery({ run: id, tab: "report" }), [setQuery]);

  const unlockedTabs = useMemo(() => {
    const set = new Set<WorkspaceTab>(["input"]);
    if (runId) {
      ["surface", "scenarios", "scripts", "run", "report"].forEach((t) =>
        set.add(t as WorkspaceTab),
      );
    }
    return set;
  }, [runId]);

  return (
    <AppShell title={story?.title} showBack activeNav="workspace">
      <PipelineStepper activeTab={activeTab} onTabChange={onTabChange} unlockedTabs={unlockedTabs} />
      <div className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-[1fr_240px]">
        <div>
          {activeTab === "input" && (
            <InputTab storyId={storyId} onRunStarted={onRunStarted} onTabChange={() => onTabChange("surface")} />
          )}
          {activeTab === "surface" && (
            <SurfaceMapTab runId={runId} onTabChange={() => onTabChange("scenarios")} />
          )}
          {activeTab === "scenarios" && (
            <ScenariosTab runId={runId} onTabChange={() => onTabChange("scripts")} />
          )}
          {activeTab === "scripts" && (
            <Suspense fallback={<TabFallback />}>
              <ScriptsTab runId={runId} onTabChange={() => onTabChange("run")} />
            </Suspense>
          )}
          {activeTab === "run" && (
            <RunTab runId={runId} onTabChange={() => onTabChange("report")} />
          )}
          {activeTab === "report" && (
            <Suspense fallback={<TabFallback />}>
              <ReportTab runId={runId} storyTitle={story?.title} />
            </Suspense>
          )}
        </div>
        <aside className="hidden lg:block">
          <RunHistorySidebar storyId={storyId} activeRunId={runId} onSelectRun={onSelectRun} />
        </aside>
      </div>
    </AppShell>
  );
}
