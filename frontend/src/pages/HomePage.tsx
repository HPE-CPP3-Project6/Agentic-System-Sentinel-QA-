import { useMemo, useState } from "react";
import { Link } from "wouter";
import { formatDistanceToNow } from "date-fns";
import {
  CheckCircle2,
  ChevronDown,
  Cloud,
  Filter,
  Play,
  Plus,
  Sun,
} from "lucide-react";
import { useCreateStory, useStories } from "@/api/hooks";
import { AppShell } from "@/components/AppShell";
import { BulkUploadDropzone } from "@/components/BulkUploadDropzone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";

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
                      <th className="w-10">S</th>
                      <th className="w-10">H</th>
                      <th>Name</th>
                      <th>ACs</th>
                      <th>Last updated</th>
                      <th className="w-16">Run</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stories.map((story) => (
                      <tr key={story.id}>
                        <td>
                          <CheckCircle2
                            className="h-4 w-4 text-success"
                            strokeWidth={1.75}
                            aria-label="Ready"
                          />
                        </td>
                        <td>
                          <Sun className="h-4 w-4 text-caution" strokeWidth={1.75} aria-label="Stable" />
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
                        <td className="text-muted">
                          {story.created_at
                            ? formatDistanceToNow(new Date(story.created_at), { addSuffix: true })
                            : "—"}
                        </td>
                        <td>
                          <Link href={`/workspace/${story.id}?tab=input`}>
                            <Button size="icon" variant="ghost" aria-label="Open workspace">
                              <Play className="h-4 w-4 text-success" strokeWidth={1.75} />
                            </Button>
                          </Link>
                        </td>
                      </tr>
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
