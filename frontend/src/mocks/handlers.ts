import { http, HttpResponse } from "msw";
import { mockArtifact, mockRunSummary, mockRuns, mockScript, mockStories } from "./data";

const stories = [...mockStories];
const runs: Record<string, typeof mockRunSummary> = {
  r_demo_8f: { ...mockRunSummary },
  r_nfr_sec: { ...mockRunSummary, run_id: "r_nfr_sec", status: "completed" },
};

let runCounter = 1;

export const handlers = [
  http.get("/api/health", () =>
    HttpResponse.json({ chroma_ok: true, target_app_ok: true, queue_depth: 0 }),
  ),

  http.get("/api/stories", () =>
    HttpResponse.json({ stories }),
  ),

  http.get("/api/stories/:id", ({ params }) => {
    const story = stories.find((s) => s.id === params.id);
    if (!story) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Story not found" } },
        { status: 404 },
      );
    }
    return HttpResponse.json(story);
  }),

  http.post("/api/stories", async ({ request }) => {
    const body = (await request.json()) as {
      title: string;
      body: string;
      acceptance_criteria: string[];
    };
    const story = {
      id: `story-${Date.now()}`,
      ...body,
      created_at: new Date().toISOString(),
    };
    stories.unshift(story);
    return HttpResponse.json({ story }, { status: 201 });
  }),

  http.patch("/api/stories/:id", async ({ params, request }) => {
    const idx = stories.findIndex((s) => s.id === params.id);
    if (idx === -1) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Story not found" } },
        { status: 404 },
      );
    }
    const patch = (await request.json()) as Partial<(typeof stories)[0]>;
    stories[idx] = { ...stories[idx], ...patch };
    return HttpResponse.json(stories[idx]);
  }),

  http.post("/api/stories/bulk", async ({ request }) => {
    const form = await request.formData();
    const file = form.get("file");
    if (!(file instanceof File)) {
      return HttpResponse.json(
        { error: { code: "bulk_parse_failed", message: "No file" } },
        { status: 422 },
      );
    }
    const text = await file.text();
    const lines = text.trim().split("\n").slice(1);
    const created = lines.map((line, i) => {
      const [title, ...rest] = line.split(",");
      return {
        id: `bulk-${Date.now()}-${i}`,
        title: title?.trim() || `Imported ${i + 1}`,
        body: rest.join(",").trim() || "Imported story",
        acceptance_criteria: ["Given imported, When saved, Then it appears in list."],
        created_at: new Date().toISOString(),
      };
    });
    stories.unshift(...created);
    return HttpResponse.json({ created, rejected: [] }, { status: 201 });
  }),

  http.get("/api/stories/:id/runs", ({ params }) =>
    HttpResponse.json({ runs: mockRuns[params.id as string] ?? [] }),
  ),

  http.post("/api/stories/:id/runs", async ({ request, params }) => {
    const runId = `r_${++runCounter}`;
    const body = (await request.json()) as { stop_after?: string | null };
    runs[runId] = {
      ...mockRunSummary,
      run_id: runId,
      status: body.stop_after ? "paused" : "running",
      current_phase: body.stop_after === "surface_resolver" ? "surface_resolver" : "executor",
    };
    const storyId = params.id as string;
    if (!mockRuns[storyId]) mockRuns[storyId] = [];
    mockRuns[storyId].unshift({
      run_id: runId,
      started_at: new Date().toISOString(),
      pipeline_mode: "post_code",
      run_validity: "OK",
      suite_quality: "ATTESTABLE",
      resilience_pct: 87.5,
    });
    return HttpResponse.json({ run_id: runId, status: runs[runId].status }, { status: 202 });
  }),

  http.get("/api/runs/:runId", ({ params }) => {
    const run = runs[params.runId as string];
    if (!run) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Run not found" } },
        { status: 404 },
      );
    }
    return HttpResponse.json(run);
  }),

  http.post("/api/runs/:runId/advance", ({ params }) => {
    const run = runs[params.runId as string];
    if (!run) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Run not found" } },
        { status: 404 },
      );
    }
    run.status = "paused";
    return HttpResponse.json({ run_id: run.run_id, status: "paused" }, { status: 202 });
  }),

  http.get("/api/runs/:runId/artifact", ({ params }) => {
    const run = runs[params.runId as string];
    if (!run) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Run not found" } },
        { status: 404 },
      );
    }
    if (run.status !== "completed" && run.status !== "paused") {
      return HttpResponse.json(
        { error: { code: "run_not_complete", message: "Run not complete" } },
        { status: 409 },
      );
    }
    return HttpResponse.json(mockArtifact);
  }),

  http.get("/api/runs/:runId/script", ({ params }) => {
    const run = runs[params.runId as string];
    if (!run) {
      return HttpResponse.json(
        { error: { code: "not_found", message: "Run not found" } },
        { status: 404 },
      );
    }
    return new HttpResponse(mockScript, {
      headers: { "Content-Type": "text/x-python" },
    });
  }),

  http.patch("/api/runs/:runId/surface-overrides", () =>
    HttpResponse.json({ surface_map: mockArtifact.surface_map }),
  ),

  http.patch("/api/runs/:runId/test-cases/:tcId", ({ params }) => {
    const tc = mockArtifact.test_suite?.find((t) => t.test_id === params.tcId);
    return HttpResponse.json(tc ?? {});
  }),

  http.post("/api/runs/:runId/patches/:patchId/decision", () =>
    HttpResponse.json({ patch_id: "p1", decision: "accept" }),
  ),
];
