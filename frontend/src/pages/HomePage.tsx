import { useMemo, useState } from "react";
import { Link } from "wouter";
import { toast } from "sonner";
import { formatDistanceToNow } from "date-fns";
import {
  ChevronDown,
  ChevronRight,
  Cloud,
  FileText,
  Filter,
  Loader2,
  Play,
  Plus,
  Trash2,
} from "lucide-react";
import { ApiError } from "@/api/client";
import {
  useCreateStory,
  useDeleteStory,
  useStartRun,
  useStories,
  useStoryRuns,
} from "@/api/hooks";
import type { RunHistoryItem, Story } from "@/api/types";
import { AppShell } from "@/components/AppShell";
import { BulkUploadDropzone } from "@/components/BulkUploadDropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/cn";

export function HomePage() {
  const { data: stories, isLoading } = useStories();
  const createStory = useCreateStory();
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [acs, setAcs] = useState("");
  const [filter, setFilter] = useState("all");

  const acList = useMemo(
    () => acs.split("\n").map((l) => l.trim()).filter(Boolean),
    [acs],
  );

  async function handleCreate() {
    if (!title.trim() || acList.length === 0) return;
    const story = await createStory.mutateAsync({
      title: title.trim(),
      body: body.trim(),
      acceptance_criteria: acList,
    });
    setShowCreate(false);
    window.location.href = `/workspace/${story.id}?tab=input`;
  }

  return (
    <AppShell activeNav="stories">
      <div className="border-b border-border bg-surface px-4 py-3">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <h1 className="text-lg font-semibold text-foreground">Your Stories</h1>
          <div className="flex items-center gap-2">
            <Input placeholder="Search stories…" className="w-48" />
            <Button onClick={() => setShowCreate((v) => !v)}>
              <Plus className="h-4 w-4" strokeWidth={1.75} />
              New Story
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-[1fr_220px]">
        <div className="space-y-4">
          {showCreate && (
            <div className="panel">
              <div className="panel-header">Create story</div>
              <div className="space-y-3 p-4">
                <div>
                  <Label htmlFor="title">Title</Label>
                  <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
                </div>
                <div>
                  <Label htmlFor="body">Story</Label>
                  <Textarea id="body" value={body} onChange={(e) => setBody(e.target.value)} rows={3} />
                </div>
                <div>
                  <Label htmlFor="ac">Acceptance criteria</Label>
                  <Textarea id="ac" value={acs} onChange={(e) => setAcs(e.target.value)} rows={4} />
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
                  <Button onClick={() => void handleCreate()} disabled={!title.trim() || !acList.length}>
                    Create & open workspace
                  </Button>
                </div>
              </div>
            </div>
          )}

          <BulkUploadDropzone />

          <div className="panel overflow-hidden">
            <div className="panel-header flex items-center justify-between">
              <span>Story list</span>
              <span className="font-normal normal-case text-muted">{stories?.length ?? 0} items</span>
            </div>
            {isLoading ? (
              <p className="p-4 text-muted">Loading…</p>
            ) : !stories?.length ? (
              <p className="p-4 text-muted">No stories. Click New Story to begin.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th className="w-8" aria-label="Expand" />
                      <th>Name</th>
                      <th className="w-14">ACs</th>
                      <th>Last run</th>
                      <th className="w-16">Runs</th>
                      <th>Updated</th>
                      <th className="w-52">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stories.map((story) => (
                      <StoryRow key={story.id} story={story} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>

        <aside className="panel h-fit">
          <div className="panel-header flex items-center gap-2">
            <Filter className="h-3.5 w-3.5" strokeWidth={1.75} />
            Filter
          </div>
          <div className="space-y-3 p-3 text-xs">
            <div>
              <Label>Sort by</Label>
              <button type="button" className="mt-1 flex w-full items-center justify-between border border-border bg-surface px-2 py-1.5">
                Last updated
                <ChevronDown className="h-3 w-3" strokeWidth={1.75} />
              </button>
            </div>
            <div>
              <Label>Validity</Label>
              <div className="mt-1 space-y-1">
                {["all", "OK", "DESIGN_ONLY"].map((v) => (
                  <label key={v} className="flex cursor-pointer items-center gap-2 normal-case">
                    <input
                      type="radio"
                      name="validity"
                      checked={filter === v}
                      onChange={() => setFilter(v)}
                    />
                    {v === "all" ? "All stories" : v}
                  </label>
                ))}
              </div>
            </div>
            <div className="border-t border-border pt-2 text-muted">
              <Cloud className="mb-1 inline h-3.5 w-3.5" strokeWidth={1.75} /> Jenkins-style job list layout
            </div>
          </div>
        </aside>
      </div>
    </AppShell>
  );
}

type BadgeVariant = "default" | "success" | "caution" | "danger" | "muted";

/** Map a run's status + validity to a single, honest last-run badge. */
function lastRunBadge(
  run: RunHistoryItem | undefined,
): { variant: BadgeVariant; label: string; spin?: boolean } {
  if (!run) return { variant: "muted", label: "Never run" };
  if (run.status === "running" || run.status === "queued") {
    return { variant: "caution", label: "Running", spin: true };
  }
  if (run.status === "failed") return { variant: "danger", label: "Failed" };
  switch (run.run_validity) {
    case "OK":
      return { variant: "success", label: "OK" };
    case "DESIGN_ONLY":
      return { variant: "default", label: "Design only" };
    case "FUNCTIONALLY_UNRELIABLE":
      return { variant: "caution", label: "Unreliable" };
    default:
      return { variant: "muted", label: run.run_validity };
  }
}

const modeLabel = (m: string) => (/pre/i.test(m) ? "PRE" : "POST");

/** A run is viewable as a report once it has finished (completed, or older
 *  history items that carry a validity but no live status). */
function isReportable(run: RunHistoryItem): boolean {
  return run.status === "completed" || (run.status == null && Boolean(run.run_validity));
}

/**
 * One story = one "job" row (Jenkins-style): last-run status at a glance, with
 * two distinct actions — Run (starts a fresh run) and View report (jumps to the
 * latest finished run's report) — plus an expandable history of earlier runs.
 */
function StoryRow({ story }: { story: Story }) {
  const [expanded, setExpanded] = useState(false);
  const { data: runs, isLoading: runsLoading } = useStoryRuns(story.id);
  const startRun = useStartRun(story.id);
  const deleteStory = useDeleteStory();

  const sorted = useMemo(
    () => [...(runs ?? [])].sort((a, b) => b.started_at.localeCompare(a.started_at)),
    [runs],
  );
  const latest = sorted[0];
  const reportRun = sorted.find(isReportable);
  const badge = lastRunBadge(latest);
  const hasActiveRun =
    latest?.status === "running" || latest?.status === "queued";

  async function handleRun() {
    try {
      const res = await startRun.mutateAsync({ mode: "post_code", stop_after: null });
      window.location.href = `/workspace/${story.id}?run=${res.run_id}&tab=surface&flow=auto`;
    } catch {
      toast.error("Could not start run");
    }
  }

  async function handleDelete() {
    if (
      !window.confirm(
        `Delete "${story.title}"?\n\nAll run history for this story will be removed. This cannot be undone.`,
      )
    ) {
      return;
    }
    try {
      await deleteStory.mutateAsync(story.id);
      toast.success("Story deleted");
    } catch (err) {
      const msg =
        err instanceof ApiError && err.code === "run_in_progress"
          ? "Wait for the current run to finish before deleting."
          : "Could not delete story";
      toast.error(msg);
    }
  }

  return (
    <>
      <tr>
        <td>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            disabled={sorted.length === 0}
            aria-label={expanded ? "Collapse run history" : "Expand run history"}
            className="grid h-6 w-6 place-items-center text-muted enabled:hover:text-foreground disabled:opacity-30"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
            )}
          </button>
        </td>
        <td>
          <Link href={`/workspace/${story.id}?tab=input`} className="font-medium no-underline">
            {story.title}
          </Link>
          <p className="text-xs text-muted">{story.id}</p>
        </td>
        <td>
          <Badge variant="outline">{story.acceptance_criteria.length}</Badge>
        </td>
        <td>
          {runsLoading && !latest ? (
            <span className="text-xs text-muted">…</span>
          ) : (
            <div className="flex items-center gap-2">
              <Badge variant={badge.variant} className="normal-case">
                {badge.spin && <Loader2 className="mr-1 inline h-3 w-3 animate-spin" aria-hidden />}
                {badge.label}
              </Badge>
              {latest && (
                <span className="text-xs text-muted">{modeLabel(latest.pipeline_mode)}</span>
              )}
              {latest?.resilience_pct != null && (
                <span className="text-xs text-muted">{latest.resilience_pct}%</span>
              )}
            </div>
          )}
        </td>
        <td className="text-muted">{sorted.length || "—"}</td>
        <td className="text-muted">
          {story.updated_at || story.created_at
            ? formatDistanceToNow(new Date((story.updated_at ?? story.created_at)!), {
                addSuffix: true,
              })
            : "—"}
        </td>
        <td>
          <div className="flex items-center gap-1.5">
            <Button size="sm" onClick={() => void handleRun()} disabled={startRun.isPending}>
              {startRun.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
              ) : (
                <Play className="h-3.5 w-3.5" strokeWidth={1.75} />
              )}
              Run
            </Button>
            {reportRun ? (
              <Link href={`/workspace/${story.id}?run=${reportRun.run_id}&tab=report`}>
                <Button size="sm" variant="outline">
                  <FileText className="h-3.5 w-3.5" strokeWidth={1.75} />
                  Report
                </Button>
              </Link>
            ) : (
              <Button size="sm" variant="outline" disabled title="No completed run yet">
                <FileText className="h-3.5 w-3.5" strokeWidth={1.75} />
                Report
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleDelete()}
              disabled={hasActiveRun || deleteStory.isPending}
              title={
                hasActiveRun
                  ? "Cannot delete while a run is in progress"
                  : "Delete story"
              }
              aria-label={`Delete ${story.title}`}
            >
              {deleteStory.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.75} />
              ) : (
                <Trash2 className="h-3.5 w-3.5 text-danger" strokeWidth={1.75} />
              )}
            </Button>
          </div>
        </td>
      </tr>

      {expanded && sorted.length > 0 && (
        <tr>
          <td colSpan={7} className="bg-surface-elevated/40 p-0">
            <div className="divide-y divide-border px-4 py-1">
              {sorted.map((run) => {
                const rb = lastRunBadge(run);
                return (
                  <div
                    key={run.run_id}
                    className="flex flex-wrap items-center gap-3 py-2 text-xs"
                  >
                    <span className="font-mono text-foreground">{run.run_id}</span>
                    <Badge variant="outline" className="normal-case">
                      {modeLabel(run.pipeline_mode)}
                    </Badge>
                    <Badge variant={rb.variant} className="normal-case">
                      {rb.label}
                    </Badge>
                    {run.resilience_pct != null && (
                      <span className="text-muted">{run.resilience_pct}% resilient</span>
                    )}
                    <span className="text-muted">
                      {formatDistanceToNow(new Date(run.started_at), { addSuffix: true })}
                    </span>
                    <span className="ml-auto">
                      {isReportable(run) ? (
                        <Link
                          href={`/workspace/${story.id}?run=${run.run_id}&tab=report`}
                          className={cn("font-medium text-primary no-underline hover:underline")}
                        >
                          Report →
                        </Link>
                      ) : (
                        <Link
                          href={`/workspace/${story.id}?run=${run.run_id}&tab=surface`}
                          className="text-muted no-underline hover:underline"
                        >
                          Open →
                        </Link>
                      )}
                    </span>
                  </div>
                );
              })}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
