import { useEffect, useState } from "react";
import type { RunHistoryItem } from "@/api/types";
import { runDurationLabel } from "@/lib/runDuration";
import { cn } from "@/lib/cn";

/** Ticks every second while a run is in-flight so elapsed time stays current. */
export function RunDuration({
  run,
  className,
}: {
  run: Pick<RunHistoryItem, "started_at" | "finished_at" | "status">;
  className?: string;
}) {
  const live = !run.finished_at && (run.status === "running" || run.status === "queued");
  const [, tick] = useState(0);

  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [live]);

  const { text } = runDurationLabel(run);

  return (
    <span className={cn("tabular-nums", className)} title={live ? "Elapsed time (still running)" : "Total run duration"}>
      {text}
    </span>
  );
}
