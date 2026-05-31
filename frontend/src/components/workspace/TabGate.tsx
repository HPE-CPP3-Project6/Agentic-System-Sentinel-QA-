import { ArrowLeft, Loader2 } from "lucide-react";
import type { WorkspaceTab } from "@/api/types";
import { Button } from "@/components/ui/button";

interface TabGateProps {
  title: string;
  detail: string;
  backLabel: string;
  onGoBack: () => void;
  loading?: boolean;
}

/** Shown when the user opens a pipeline tab before its gate is satisfied. */
export function TabGate({
  title,
  detail,
  backLabel,
  onGoBack,
  loading,
}: TabGateProps) {
  return (
    <div className="panel p-6 space-y-4">
      {loading && (
        <div className="flex items-center gap-2 text-sm text-muted">
          <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
          Waiting for backend…
        </div>
      )}
      <div>
        <p className="font-semibold text-foreground">{title}</p>
        <p className="mt-1 text-sm text-muted">{detail}</p>
      </div>
      <Button size="sm" variant="outline" onClick={onGoBack}>
        <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
        {backLabel}
      </Button>
    </div>
  );
}

export const TAB_LABELS: Record<WorkspaceTab, string> = {
  input: "Input",
  surface: "Surface Map",
  scenarios: "Scenarios",
  scripts: "Scripts",
  run: "Run",
  report: "Report",
};
