import { useEffect, useMemo, useState } from "react";
import { Play, Zap } from "lucide-react";
import { toast } from "sonner";
import type { FlowMode } from "@/api/pipelineSettings";
import { pipelineModeLabel } from "@/api/pipelineSettings";
import { ApiError } from "@/api/client";
import { useStartRun, useStory, useUpdateStory } from "@/api/hooks";
import type { PipelineMode } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/cn";

interface InputTabProps {
  storyId: string;
  flowMode: FlowMode;
  pipelineMode: PipelineMode;
  onFlowModeChange: (mode: FlowMode) => void;
  onPipelineModeChange: (mode: PipelineMode) => void;
  onRunStarted: (runId: string) => void;
}

export function InputTab({
  storyId,
  flowMode,
  pipelineMode,
  onFlowModeChange,
  onPipelineModeChange,
  onRunStarted,
}: InputTabProps) {
  const { data: story, isError, error, isLoading } = useStory(storyId);
  const updateStory = useUpdateStory(storyId);
  const startRun = useStartRun(storyId);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [acs, setAcs] = useState("");

  useEffect(() => {
    if (story) {
      setTitle(story.title);
      setBody(story.body);
      setAcs(story.acceptance_criteria.join("\n"));
    }
  }, [story]);

  const acList = useMemo(
    () => acs.split("\n").map((l) => l.trim()).filter(Boolean),
    [acs],
  );

  const valid = title.trim().length > 0 && acList.length > 0 && acList.length <= 30;

  async function save() {
    await updateStory.mutateAsync({
      title: title.trim(),
      body: body.trim(),
      acceptance_criteria: acList,
    });
    toast.success("Story saved");
  }

  async function startPipeline() {
    await save();
    const auto = flowMode === "auto";
    const result = await startRun.mutateAsync({
      mode: pipelineMode,
      stop_after: auto ? null : "surface_resolver",
    });
    onRunStarted(result.run_id);
    toast.success(
      auto
        ? "Full pipeline started — tabs will advance automatically"
        : "Surface resolution started",
    );
  }

  if (isLoading && !story) {
    return <p className="p-4 text-muted">Loading story…</p>;
  }
  if (isError || !story) {
    const missing = error instanceof ApiError && error.code === "not_found";
    return (
      <div className="panel space-y-3 p-6">
        <p className="font-semibold text-foreground">
          {missing ? "Story not found" : "Could not load story"}
        </p>
        <p className="text-sm text-muted">
          {missing
            ? "It may have been deleted. Return to Stories and open another workspace."
            : error instanceof Error
              ? error.message
              : "Check that the API shim is running."}
        </p>
        <a href="/" className="text-sm font-medium text-primary no-underline hover:underline">
          Back to Stories
        </a>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">Story input</div>
      <div className="space-y-4 p-4">
        <div className="grid gap-4 border-b border-border pb-4 md:grid-cols-2">
          <div>
            <Label>Pipeline type</Label>
            <Select
              className="mt-1 w-full"
              value={pipelineMode}
              onChange={(e) => onPipelineModeChange(e.target.value as PipelineMode)}
            >
              <option value="post_code">Post-code — ground against repo + run pytest</option>
              <option value="pre_code">Pre-code — design contracts only (no execution)</option>
            </Select>
            <p className="mt-1 text-xs text-muted">{pipelineModeLabel(pipelineMode)}</p>
          </div>
          <div>
            <Label>Run flow</Label>
            <div className="mt-1 flex gap-2">
              <FlowToggle
                active={flowMode === "regular"}
                label="Regular"
                detail="Pause at each gate; you review and continue"
                onClick={() => onFlowModeChange("regular")}
              />
              <FlowToggle
                active={flowMode === "auto"}
                label="Auto"
                detail="Run all phases; UI follows progress"
                onClick={() => onFlowModeChange("auto")}
              />
            </div>
          </div>
        </div>

        <div>
          <Label htmlFor="title">Title</Label>
          <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="body">User story</Label>
          <Textarea id="body" value={body} onChange={(e) => setBody(e.target.value)} rows={4} />
        </div>
        <div>
          <Label htmlFor="ac">Acceptance criteria (one per line)</Label>
          <Textarea id="ac" value={acs} onChange={(e) => setAcs(e.target.value)} rows={6} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          <span className="text-xs text-muted">
            {acList.length} acceptance criteria · {pipelineModeLabel(pipelineMode)} ·{" "}
            <Badge variant="outline" className="normal-case">{flowMode}</Badge>
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void save()} disabled={!valid}>
              Save
            </Button>
            {flowMode === "auto" ? (
              <Button onClick={() => void startPipeline()} disabled={!valid || startRun.isPending}>
                <Zap className="h-4 w-4" strokeWidth={1.75} />
                Run full pipeline
              </Button>
            ) : (
              <Button onClick={() => void startPipeline()} disabled={!valid || startRun.isPending}>
                <Play className="h-4 w-4" strokeWidth={1.75} />
                Resolve Surface
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function FlowToggle({
  active,
  label,
  detail,
  onClick,
}: {
  active: boolean;
  label: string;
  detail: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex-1 border px-3 py-2 text-left text-xs transition-colors",
        active
          ? "border-primary bg-surface-elevated text-foreground"
          : "border-border bg-surface text-muted hover:bg-surface-elevated",
      )}
    >
      <span className="font-semibold uppercase tracking-wide">{label}</span>
      <span className="mt-0.5 block normal-case text-muted">{detail}</span>
    </button>
  );
}
