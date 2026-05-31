import { z } from "zod";

export const SurfaceStateSchema = z.enum([
  "BACKEND_API",
  "FRONTEND_ONLY",
  "CLIENT_SIDE_ONLY",
  "NOT_IMPLEMENTED",
  "NEEDS_CLARIFICATION",
]);

export const ThreatClassSchema = z.enum([
  "DEFENSIVE_NORMAL",
  "DEFENSIVE_INVERTED",
  "NON_FUNCTIONAL",
]);

export const DefenseKindSchema = z.enum([
  "INPUT_REJECTION",
  "TRANSPORT",
  "OUTPUT_REDACTION",
  "IMPLICIT_FILTER",
  "ERROR_SANITIZATION",
]);

export const PipelineModeSchema = z.enum(["pre_code", "post_code", "PRE_CODE", "POST_CODE"]);
export const RunValiditySchema = z.enum([
  "OK",
  "FUNCTIONALLY_UNRELIABLE",
  "DESIGN_ONLY",
]);

export const SuiteQualitySchema = z.enum([
  "ATTESTABLE",
  "INSUFFICIENT",
  "PROXY_HEAVY",
  "NO_RISKS_PREDICTED",
  "ALL_SKIPPED",
  "NO_TESTS_GENERATED",
  "DESIGN_COMPLETE",
  "DESIGN_INSUFFICIENT",
]);

export const StorySchema = z.object({
  id: z.string(),
  title: z.string(),
  body: z.string(),
  acceptance_criteria: z.array(z.string()),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

export const RunStatusSchema = z.enum([
  "queued",
  "running",
  "paused",
  "completed",
  "failed",
]);

export const PhaseNameSchema = z.enum([
  "critic",
  "surface_resolver",
  "generator",
  "security_compiler",
  "compiler",
  "executor",
]);

export const RunPhaseSchema = z.object({
  phase: PhaseNameSchema,
  status: z.enum(["pending", "running", "completed", "failed"]),
  duration_ms: z.number().optional(),
  started_at: z.string().optional(),
});

export const RunSummarySchema = z.object({
  run_id: z.string(),
  status: RunStatusSchema,
  current_phase: PhaseNameSchema.nullable().optional(),
  phases: z.array(RunPhaseSchema).default([]),
  partial_artifact: z.record(z.string(), z.unknown()).optional(),
});

export const RunHistoryItemSchema = z.object({
  run_id: z.string(),
  started_at: z.string(),
  pipeline_mode: PipelineModeSchema,
  run_validity: RunValiditySchema,
  suite_quality: SuiteQualitySchema.nullish(),
  resilience_pct: z.number().nullish(),
});

export const BackendEndpointSchema = z.object({
  method: z.string(),
  path: z.string(),
  handler_file: z.string().optional(),
  handler_line: z.number().optional(),
});

export const SurfaceBindingSchema = z.object({
  req_id: z.string(),
  requirement_text: z.string().optional(),
  state: SurfaceStateSchema,
  threat_class: ThreatClassSchema.optional(),
  defense_kind: DefenseKindSchema.optional(),
  backend_endpoints: z.array(BackendEndpointSchema).default([]),
  grounding_refs: z.array(z.string()).default([]),
  confidence: z.enum(["high", "medium", "low"]).optional(),
  assertion_hint: z.string().optional(),
});

export const TestCaseSchema = z.object({
  test_id: z.string(),
  title: z.string().optional(),
  category: z.string().optional(),
  technique: z.string().optional(),
  equivalence_class: z.string().optional(),
  method: z.string().optional(),
  path: z.string().optional(),
  expected_status_code: z.number().optional(),
  adversarial: z.boolean().optional(),
  input_data: z.record(z.string(), z.unknown()).optional(),
  forbidden_response_content: z.array(z.string()).optional(),
  source_refs: z.array(z.string()).optional(),
});

export const VerdictRecordSchema = z.object({
  test_id: z.string(),
  status: z.enum(["passed", "failed", "skipped", "error"]),
  verdict: z
    .enum(["resilient", "vulnerable", "off_target", "inconclusive", "n/a"])
    .optional(),
  verdict_confidence: z.enum(["high", "medium", "low"]).optional(),
  duration_ms: z.number().optional(),
  exploit_target: z.string().optional(),
});

export const SuggestedPatchSchema = z.object({
  patch_id: z.string(),
  test_id: z.string(),
  summary: z.string(),
  decision: z.enum(["pending", "accept", "reject"]).optional(),
});

export const SecurityPostureSchema = z.object({
  attempted: z.number().optional(),
  resilient: z.number().optional(),
  vulnerable: z.number().optional(),
  skipped: z.number().optional(),
  errored: z.number().optional(),
  resilience_pct: z.number().optional(),
  by_exploit_target: z
    .record(
      z.string(),
      z.object({
        attempted: z.number().optional(),
        resilient: z.number().optional(),
        vulnerable: z.number().optional(),
        skipped: z.number().optional(),
        errored: z.number().optional(),
      }),
    )
    .optional(),
});

export const ProjectStateSchema = z
  .object({
    pipeline_mode: PipelineModeSchema,
    run_validity: RunValiditySchema,
    coverage_quality: SuiteQualitySchema.optional(),
    suite_quality: SuiteQualitySchema.optional(),
    attestation_banner: z.string().optional(),
    surface_map: z.record(z.string(), SurfaceBindingSchema).optional(),
    test_suite: z.array(TestCaseSchema).optional(),
    execution_logs: z.array(VerdictRecordSchema).optional(),
    design_contracts: z.array(z.record(z.string(), z.unknown())).optional(),
    security_checklist: z.array(z.record(z.string(), z.unknown())).optional(),
    design_summary: z.string().optional(),
    suggested_patches: z.array(SuggestedPatchSchema).optional(),
    security_posture: SecurityPostureSchema.optional(),
    test_suite_summary: z.record(z.string(), z.unknown()).optional(),
    resilience_pct: z.number().optional(),
    drift_report: z.record(z.string(), z.unknown()).optional(),
    sast_summary: z.record(z.string(), z.unknown()).optional(),
    metadata: z.record(z.string(), z.unknown()).optional(),
  })
  .passthrough();

export const HealthSchema = z.object({
  chroma_ok: z.boolean(),
  target_app_ok: z.boolean(),
  queue_depth: z.number().optional(),
});

export const ApiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    message: z.string(),
    detail: z.record(z.string(), z.unknown()).optional(),
  }),
});

export type Story = z.infer<typeof StorySchema>;
export type RunSummary = z.infer<typeof RunSummarySchema>;
export type RunHistoryItem = z.infer<typeof RunHistoryItemSchema>;
export type ProjectState = z.infer<typeof ProjectStateSchema>;
export type SurfaceBinding = z.infer<typeof SurfaceBindingSchema>;
export type TestCase = z.infer<typeof TestCaseSchema>;
export type VerdictRecord = z.infer<typeof VerdictRecordSchema>;
export type SuggestedPatch = z.infer<typeof SuggestedPatchSchema>;
export type SecurityPosture = z.infer<typeof SecurityPostureSchema>;
export type Health = z.infer<typeof HealthSchema>;
export type PipelineMode = z.infer<typeof PipelineModeSchema>;
export type SuiteQuality = z.infer<typeof SuiteQualitySchema>;
export type RunStatus = z.infer<typeof RunStatusSchema>;
export type PhaseName = z.infer<typeof PhaseNameSchema>;

export type WorkspaceTab =
  | "input"
  | "surface"
  | "scenarios"
  | "scripts"
  | "run"
  | "report";

export const WORKSPACE_TABS: { id: WorkspaceTab; label: string; step: number }[] = [
  { id: "input", label: "Input", step: 1 },
  { id: "surface", label: "Surface Map", step: 2 },
  { id: "scenarios", label: "Scenarios", step: 3 },
  { id: "scripts", label: "Scripts", step: 4 },
  { id: "run", label: "Run", step: 5 },
  { id: "report", label: "Report", step: 6 },
];

export function isPreCode(mode?: string): boolean {
  return mode?.toLowerCase() === "pre_code";
}

export type WsEvent =
  | {
      type: "phase_started";
      run_id: string;
      seq: number;
      ts: string;
      phase: PhaseName;
      index: number;
      total: number;
    }
  | {
      type: "phase_completed";
      run_id: string;
      seq: number;
      ts: string;
      phase: PhaseName;
      duration_ms: number;
      summary?: Record<string, number>;
    }
  | {
      type: "pytest_stdout";
      run_id: string;
      seq: number;
      ts: string;
      stream: "stdout" | "stderr";
      line: string;
    }
  | {
      type: "verdict_decided";
      run_id: string;
      seq: number;
      ts: string;
      test_id: string;
      status: VerdictRecord["status"];
      verdict?: VerdictRecord["verdict"];
      verdict_confidence?: VerdictRecord["verdict_confidence"];
      duration_ms?: number;
      exploit_target?: string;
    }
  | {
      type: "run_paused";
      run_id: string;
      seq: number;
      ts: string;
      stopped_after: PhaseName;
    }
  | {
      type: "run_completed";
      run_id: string;
      seq: number;
      ts: string;
      pipeline_mode: PipelineMode;
      run_validity: z.infer<typeof RunValiditySchema>;
      suite_quality?: SuiteQuality;
      resilience_pct?: number;
    }
  | {
      type: "run_failed";
      run_id: string;
      seq: number;
      ts: string;
      code: string;
      phase?: PhaseName;
      message: string;
    };
