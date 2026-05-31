import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "./client";
import type {
  Health,
  PipelineMode,
  ProjectState,
  RunHistoryItem,
  RunSummary,
  Story,
  TestCase,
} from "./types";
import {
  HealthSchema,
  ProjectStateSchema,
  RunHistoryItemSchema,
  RunSummarySchema,
  StorySchema,
} from "./types";
import { z } from "zod";
import { isArtifactReady, isRunInFlight } from "./runLifecycle";

export const queryKeys = {
  stories: ["stories"] as const,
  story: (id: string) => ["story", id] as const,
  run: (id: string) => ["run", id] as const,
  artifact: (id: string) => ["run", id, "artifact"] as const,
  storyRuns: (storyId: string) => ["story", storyId, "runs"] as const,
  health: ["health"] as const,
  script: (runId: string) => ["run", runId, "script"] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: async () => {
      const data = await apiFetch<Health>("/api/health");
      return HealthSchema.parse(data);
    },
    refetchInterval: 30_000,
  });
}

export function useStories() {
  return useQuery({
    queryKey: queryKeys.stories,
    queryFn: async () => {
      const data = await apiFetch<{ stories: Story[] }>("/api/stories");
      return z.array(StorySchema).parse(data.stories);
    },
  });
}

export function useStory(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.story(id ?? ""),
    queryFn: async () => {
      const data = await apiFetch<Story>(`/api/stories/${id}`);
      return StorySchema.parse(data);
    },
    enabled: Boolean(id),
  });
}

export function useCreateStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      title: string;
      body: string;
      acceptance_criteria: string[];
    }) => {
      const data = await apiFetch<{ story: Story }>("/api/stories", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      return StorySchema.parse(data.story ?? data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.stories }),
  });
}

export function useUpdateStory(storyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      payload: Partial<Pick<Story, "title" | "body" | "acceptance_criteria">>,
    ) => {
      const data = await apiFetch<Story>(`/api/stories/${storyId}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      return StorySchema.parse(data);
    },
    onSuccess: (story) => {
      qc.setQueryData(queryKeys.story(storyId), story);
      qc.invalidateQueries({ queryKey: queryKeys.stories });
    },
  });
}

export function useBulkUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return apiFetch<{
        created: Story[];
        rejected: { row: number; reason: string }[];
      }>("/api/stories/bulk", { method: "POST", body: form });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.stories }),
  });
}

export function useStartRun(storyId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      mode: PipelineMode;
      stop_after?: "surface_resolver" | "compiler" | null;
    }) => {
      return apiFetch<{ run_id: string; status: string }>(
        `/api/stories/${storyId}/runs`,
        { method: "POST", body: JSON.stringify(payload) },
      );
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: queryKeys.storyRuns(storyId) });
      if (result.run_id) {
        qc.invalidateQueries({ queryKey: queryKeys.run(result.run_id) });
      }
    },
  });
}

export function useAdvanceRun(runId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: { stop_after?: "compiler" | null }) => {
      return apiFetch<{ run_id: string; status: string }>(
        `/api/runs/${runId}/advance`,
        { method: "POST", body: JSON.stringify(payload) },
      );
    },
    onSuccess: async () => {
      if (runId) {
        await qc.invalidateQueries({ queryKey: queryKeys.run(runId) });
        await qc.refetchQueries({ queryKey: queryKeys.run(runId) });
        qc.invalidateQueries({ queryKey: queryKeys.artifact(runId) });
        qc.invalidateQueries({ queryKey: queryKeys.script(runId) });
      }
    },
  });
}

export function useRun(runId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: async () => {
      const data = await apiFetch<RunSummary>(`/api/runs/${runId}`);
      return RunSummarySchema.parse(data);
    },
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (isRunInFlight(status)) return 1500;
      return false;
    },
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
}

export function useArtifact(runId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.artifact(runId ?? ""),
    queryFn: async () => {
      const data = await apiFetch<ProjectState>(`/api/runs/${runId}/artifact`);
      return ProjectStateSchema.parse(data);
    },
    enabled: Boolean(runId) && enabled,
    retry: (count, error) => {
      if (error instanceof ApiError && error.code === "run_not_complete") return false;
      if (error instanceof ApiError && error.code === "script_not_ready") return false;
      return count < 2;
    },
  });
}

/** Fetch artifact only when the backend gate allows it (paused or completed). */
export function useRunArtifact(runId: string | undefined) {
  const { data: run } = useRun(runId);
  const ready = isArtifactReady(run?.status);
  const artifact = useArtifact(runId, ready);
  return { run, artifact, ready };
}

export function useStoryRuns(storyId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.storyRuns(storyId ?? ""),
    queryFn: async () => {
      const data = await apiFetch<{ runs: RunHistoryItem[] }>(
        `/api/stories/${storyId}/runs`,
      );
      return z.array(RunHistoryItemSchema).parse(data.runs);
    },
    enabled: Boolean(storyId),
    refetchInterval: 5000,
  });
}

export function useScript(runId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.script(runId ?? ""),
    queryFn: async () => {
      return apiFetch<string>(`/api/runs/${runId}/script?format=py`);
    },
    enabled: Boolean(runId) && enabled,
    retry: (count, error) => {
      if (error instanceof ApiError && error.code === "run_not_complete") return false;
      if (error instanceof ApiError && error.code === "script_not_ready") return false;
      return count < 2;
    },
  });
}

export function useSurfaceOverride(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (overrides: Record<string, unknown>) => {
      return apiFetch(`/api/runs/${runId}/surface-overrides`, {
        method: "PATCH",
        body: JSON.stringify({ overrides }),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.run(runId) });
      qc.invalidateQueries({ queryKey: queryKeys.artifact(runId) });
    },
  });
}

export function usePatchTestCase(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      tcId,
      patch,
    }: {
      tcId: string;
      patch: Partial<TestCase>;
    }) => {
      return apiFetch(`/api/runs/${runId}/test-cases/${tcId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.run(runId) });
      qc.invalidateQueries({ queryKey: queryKeys.artifact(runId) });
    },
  });
}

export function usePatchDecision(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      patchId,
      decision,
    }: {
      patchId: string;
      decision: "accept" | "reject";
    }) => {
      return apiFetch(`/api/runs/${runId}/patches/${patchId}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.artifact(runId) });
    },
  });
}
