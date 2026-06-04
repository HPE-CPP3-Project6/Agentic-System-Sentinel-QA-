import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  ChevronRight,
  Code2,
  FileText,
  GitBranch,
  ListChecks,
  Play,
} from "lucide-react";
import { WORKSPACE_TABS, type WorkspaceTab } from "@/api/types";
import { cn } from "@/lib/cn";

const TAB_ICONS: Record<WorkspaceTab, LucideIcon> = {
  input: FileText,
  surface: GitBranch,
  scenarios: ListChecks,
  scripts: Code2,
  run: Play,
  report: BarChart3,
};

interface PipelineStepperProps {
  activeTab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  unlockedTabs?: Set<WorkspaceTab>;
  /** Tabs to display — defaults to all. PRE_CODE passes a design-only subset. */
  tabs?: { id: WorkspaceTab; label: string; step: number }[];
}

export function PipelineStepper({
  activeTab,
  onTabChange,
  unlockedTabs,
  tabs = WORKSPACE_TABS,
}: PipelineStepperProps) {
  return (
    <nav
      aria-label="Pipeline steps"
      className="border-b border-border bg-surface"
    >
      <ol className="flex overflow-x-auto">
        {tabs.map((tab, i) => {
          const unlocked = !unlockedTabs || unlockedTabs.has(tab.id);
          const active = activeTab === tab.id;
          const Icon = TAB_ICONS[tab.id];
          return (
            <li key={tab.id} className="flex items-center">
              <button
                type="button"
                disabled={!unlocked}
                onClick={() => onTabChange(tab.id)}
                className={cn(
                  "flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide transition-colors",
                  active
                    ? "border-primary bg-surface-elevated text-primary"
                    : unlocked
                      ? "border-transparent text-muted hover:bg-surface-elevated hover:text-foreground"
                      : "border-transparent text-muted cursor-not-allowed opacity-40",
                )}
              >
                <Icon className="h-4 w-4" strokeWidth={1.75} aria-hidden />
                <span className="hidden sm:inline">{tab.label}</span>
              </button>
              {i < tabs.length - 1 && (
                <ChevronRight
                  className="h-3 w-3 shrink-0 text-muted"
                  strokeWidth={1.75}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
