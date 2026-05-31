import { useEffect, useMemo, useState } from "react";
import { Play } from "lucide-react";
import { toast } from "sonner";
import { useStartRun, useStory, useUpdateStory } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";

interface InputTabProps {
  storyId: string;
  onRunStarted: (runId: string) => void;
  onTabChange: (tab: "surface") => void;
}

export function InputTab({ storyId, onRunStarted, onTabChange }: InputTabProps) {
  const { data: story } = useStory(storyId);
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

  async function resolveSurface() {
    await save();
    const result = await startRun.mutateAsync({
      mode: "post_code",
      stop_after: "surface_resolver",
    });
    onRunStarted(result.run_id);
    onTabChange("surface");
    toast.success("Surface resolution started");
  }

  if (!story) return <p className="p-4 text-muted">Loading story…</p>;

  return (
    <div className="panel">
      <div className="panel-header">Story input</div>
      <div className="space-y-4 p-4">
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
            {acList.length} acceptance criteria · {title.trim() ? "title set" : "title required"}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void save()} disabled={!valid}>
              Save
            </Button>
            <Button onClick={() => void resolveSurface()} disabled={!valid || startRun.isPending}>
              <Play className="h-4 w-4" strokeWidth={1.75} />
              Resolve Surface
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
