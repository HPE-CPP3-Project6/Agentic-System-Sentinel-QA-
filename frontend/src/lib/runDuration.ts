import type { RunHistoryItem } from "@/api/types";

/** Milliseconds from started_at to finished_at, or to now for in-flight runs. */
export function computeRunDurationMs(run: Pick<RunHistoryItem, "started_at" | "finished_at" | "status">): number | null {
  const start = Date.parse(run.started_at);
  if (Number.isNaN(start)) return null;

  if (run.finished_at) {
    const end = Date.parse(run.finished_at);
    if (Number.isNaN(end)) return null;
    return Math.max(0, end - start);
  }

  if (run.status === "running" || run.status === "queued") {
    return Math.max(0, Date.now() - start);
  }

  return null;
}

export function formatDurationMs(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
}

/** Human label for story list / run history rows. */
export function runDurationLabel(
  run: Pick<RunHistoryItem, "started_at" | "finished_at" | "status">,
): { text: string; live: boolean } {
  const ms = computeRunDurationMs(run);
  if (ms == null) return { text: "—", live: false };
  const live = !run.finished_at && (run.status === "running" || run.status === "queued");
  return {
    text: live ? `${formatDurationMs(ms)} elapsed` : formatDurationMs(ms),
    live,
  };
}
