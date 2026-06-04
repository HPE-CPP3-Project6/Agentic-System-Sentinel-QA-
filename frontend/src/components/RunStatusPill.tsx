import { Badge } from "@/components/ui/badge";
import { useRun } from "@/api/hooks";
import { useUiStore } from "@/stores/uiStore";
import { useRunStreamStore } from "@/stores/runStreamStore";
import { Loader2 } from "lucide-react";

export function RunStatusPill() {
  const activeRunId = useUiStore((s) => s.activeRunId);
  const wsStatus = useUiStore((s) => s.wsStatus);
  const streamStatus = useRunStreamStore((s) => s.runStatus);
  const { data: run } = useRun(activeRunId ?? undefined);

  if (!activeRunId) return null;

  const wsActive = wsStatus === "connected" || wsStatus === "connecting";
  const displayStatus =
    wsActive && streamStatus !== "idle" ? streamStatus : (run?.status ?? "queued");

  const variant =
    displayStatus === "failed"
      ? "danger"
      : displayStatus === "completed"
        ? "success"
        : displayStatus === "running"
          ? "default"
          : displayStatus === "paused"
            ? "caution"
            : "muted";

  return (
    <Badge variant={variant} className="font-mono normal-case">
      {wsStatus === "connecting" && (
        <Loader2 className="mr-1 inline h-3 w-3 animate-spin" aria-hidden />
      )}
      {activeRunId} · {displayStatus}
    </Badge>
  );
}
