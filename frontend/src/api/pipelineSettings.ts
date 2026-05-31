import type { PipelineMode } from "./types";

export type FlowMode = "regular" | "auto";

export function parseFlowMode(raw: string | null): FlowMode {
  return raw === "auto" ? "auto" : "regular";
}

export function parsePipelineMode(raw: string | null): PipelineMode {
  if (raw === "pre_code" || raw === "PRE_CODE") return "pre_code";
  return "post_code";
}

export function pipelineModeLabel(mode: PipelineMode): string {
  return mode === "pre_code" ? "Pre-code (design)" : "Post-code (execute)";
}
