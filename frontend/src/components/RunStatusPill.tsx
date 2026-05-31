import { Badge } from "@/components/ui/badge";
import { useUiStore } from "@/stores/uiStore";
import { useRunStreamStore } from "@/stores/runStreamStore";
import { Loader2 } from "lucide-react";

export function RunStatusPill() {
  const activeRunId = useUiStore((s) => s.activeRunId);
  const wsStatus = useUiStore((s) => s.wsStatus);
  const runStatus = useRunStreamStore((s) => s.runStatus);

  if (!activeRunId) return null;

  const variant =
    runStatus === "failed"
      ? "danger"
      : runStatus === "completed"
        ? "success"
        : runStatus === "running"
          ? "default"
          : "muted";

  return (
    <Badge variant={variant} className="font-mono normal-case">
      {wsStatus === "connecting" && (
        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" aria-hidden />
      )}
      {activeRunId} · {runStatus}
    </Badge>
  );
}
