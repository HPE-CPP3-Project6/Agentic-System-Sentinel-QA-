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

// Stage-1 attestation taxonomy. The Resolver tags each binding with one
// of these (or leaves it null/untagged). Adversarial tests inherit the
// stamp from their binding; the Classifier verdict cascade uses the
// stamp as the authority. See Backend/agents/attestation.py for the
// full cascade.
//
//   missing_control     — the required defense is ABSENT in code; tests
//                         document the gap (pass = vulnerable).
//   defense_confirming  — the defense IS present; tests verify it holds
//                         (pass = resilient).
//
// A null/missing attestation_mode on an adversarial test produces an
// UNCLASSIFIED verdict (renders as "inconclusive" in the artifact and
// is counted in its own posture bucket).
export const AttestationModeSchema = z.enum([
  "missing_control",
  "defense_confirming",
]);

export const PipelineModeSchema = z.enum(["pre_code", "post_code", "PRE_CODE", "POST_CODE"]);
export const RunValiditySchema = z.enum([
  "OK",
  "FUNCTIONALLY_UNRELIABLE",
  "TARGET_UNREACHABLE",
  "DESIGN_ONLY",
  "NOT_ATTESTED",
]);

export const SuiteQualitySchema = z.enum([
  "ATTESTABLE",
  "INSUFFICIENT",
  "PROXY_HEAVY",
  // Stage-1 attestation gate: > 30% of adversarial logs were UNCLASSIFIED
  // (no Resolver stamp, no Generator stamp). The resilience % is computed
  // on a sliver of the suite — surface as its own badge instead of letting
  // the headline number lie.
  "INCONCLUSIVE_HEAVY",
  "NO_RISKS_PREDICTED",
  "ALL_SKIPPED",
  "NO_TESTS_GENERATED",
  "NO_REQUIREMENTS",
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
  stop_after: z.string().nullable().optional(),
  phases: z.array(RunPhaseSchema).default([]),
  partial_artifact: z.record(z.string(), z.unknown()).nullish(),
  error_code: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
});

export const RunHistoryItemSchema = z.object({
  run_id: z.string(),
  started_at: z.string(),
  pipeline_mode: PipelineModeSchema,
  status: RunStatusSchema.optional(),
  current_phase: PhaseNameSchema.nullable().optional(),
  run_validity: RunValiditySchema,
  suite_quality: SuiteQualitySchema.nullish(),
  resilience_pct: z.number().nullish(),
});

export const BackendEndpointSchema = z.object({
  method: z.string(),
  path: z.string(),
  // PRE_CODE bindings are design intent with no code yet, so the shim emits
  // handler_file/handler_line as null — accept null, not just undefined.
  handler_file: z.string().nullish(),
  handler_line: z.number().nullish(),
});

export const SurfaceBindingSchema = z.object({
  req_id: z.string(),
  requirement_text: z.string().nullish(),
  state: SurfaceStateSchema,
  threat_class: ThreatClassSchema.nullish(),
  defense_kind: z.string().nullish(),
  backend_endpoints: z.array(BackendEndpointSchema).default([]),
  grounding_refs: z.array(z.string()).default([]),
  confidence: z.enum(["high", "medium", "low"]).nullish(),
  assertion_hint: z.string().nullish(),
  // Stage-1 attestation taxonomy — Resolver's classification for this REQ.
  attestation_mode: AttestationModeSchema.nullish(),
});

export const TestCaseSchema = z.object({
  test_id: z.string(),
  title: z.string().nullish(),
  category: z.string().nullish(),
  technique: z.string().nullish(),
  equivalence_class: z.string().nullish(),
  method: z.string().nullish(),
  path: z.string().nullish(),
  expected_status_code: z.number().nullish(),
  adversarial: z.boolean().nullish(),
  input_data: z
    .union([z.record(z.string(), z.unknown()), z.array(z.unknown())])
    .nullish(),
  forbidden_response_content: z.array(z.string()).nullish(),
  source_refs: z.array(z.string()).nullish(),
  // Stage-1 attestation — null on functional tests; required-on-emit for
  // adversarial tests (Generator OUTPUT SCHEMA). Renders as a chip on
  // each adversarial test row so reviewers see "this test was attesting
  // a gap (missing_control)" or "this test was verifying a defense
  // (defense_confirming)" at a glance.
  attestation_mode: AttestationModeSchema.nullish(),
  // Stage-3 honest header attestation — keyed by header name (lowercase);
  // value is the required value or null for presence-only. Empty dict
  // means the test does NOT verify a response header. Populated by the
  // Generator when test title claims a header (X-Frame-Options, CSP,
  // HSTS, etc.); the harness asserts each header is actually present
  // on the response, killing the false-green pattern where status-200
  // counted as "headers OK".
  required_response_headers: z
    .record(z.string(), z.string().nullable())
    .nullish(),
});

export const VerdictRecordSchema = z.object({
  test_id: z.string(),
  status: z.enum(["passed", "failed", "skipped", "error", "off_target"]),
  verdict: z
    .enum(["resilient", "vulnerable", "off_target", "inconclusive", "n/a"])
    .nullish(),
  verdict_confidence: z.enum(["high", "medium", "low"]).nullish(),
  duration_ms: z.number().nullish(),
  exploit_target: z.string().nullish(),
  // Enriched by the shim for the findings table: evidence + provenance so a
  // reviewer can see WHY a verdict was reached without opening pytest.
  is_adversarial: z.boolean().nullish(),
  category: z.string().nullish(),
  technique: z.string().nullish(),
  title: z.string().nullish(),
  stderr_excerpt: z.string().nullish(),
  verdict_evidence: z.array(z.string()).nullish(),
  // Stage-1: the attestation mode the test was emitted with. Lets the
  // findings row show "this test was attesting a GAP" vs "this test was
  // verifying a DEFENSE" — same info that drove the verdict cascade.
  attestation_mode: AttestationModeSchema.nullish(),
});

// test_suite_summary — typed so the ISTQB technique + category rollups render.
const CategoryBucketSchema = z
  .object({
    planned: z.number().nullish(),
    executed: z.number().nullish(),
    passed: z.number().nullish(),
    failed: z.number().nullish(),
    skipped: z.number().nullish(),
    error: z.number().nullish(),
    resilient: z.number().nullish(),
    vulnerable: z.number().nullish(),
  })
  .passthrough();

export const TestSuiteSummarySchema = z
  .object({
    totals: z.object({ planned: z.number().nullish(), executed: z.number().nullish() }).nullish(),
    by_category: z.record(z.string(), CategoryBucketSchema).nullish(),
    category_order: z.array(z.string()).nullish(),
    by_technique: z
      .record(z.string(), z.object({ planned: z.number().nullish(), executed: z.number().nullish() }).passthrough())
      .nullish(),
    technique_order: z.array(z.string()).nullish(),
    equivalence_partitions: z.record(z.string(), z.record(z.string(), z.array(z.string()))).nullish(),
    by_owasp: z.record(z.string(), z.unknown()).nullish(),
  })
  .passthrough();

// design_summary — PRE_CODE rollup (now an OBJECT, was wrongly typed as string).
export const DesignSummarySchema = z
  .object({
    contracts_total: z.number().nullish(),
    contracts_by_method: z.record(z.string(), z.number()).nullish(),
    requirements_total: z.number().nullish(),
    requirements_with_contract: z.number().nullish(),
    checklist_total: z.number().nullish(),
    checklist_by_owasp: z.record(z.string(), z.number()).nullish(),
  })
  .passthrough();

export const CoverageGapSchema = z
  .object({
    requirement_id: z.string().nullish(),
    acceptance_criterion: z.string().nullish(),
    reason: z.string().nullish(),
  })
  .passthrough();

export const SuggestedPatchSchema = z.object({
  patch_id: z.string(),
  test_id: z.string(),
  summary: z.string(),
  decision: z.enum(["pending", "accept", "reject"]).optional(),
  target_file: z.string().nullish(),
  bug_explanation: z.string().nullish(),
  suggested_fix: z.string().nullish(),
  related_test_ids: z.array(z.string()).nullish(),
  owasp_category: z.string().nullish(),
});

const ExploitTargetCountsSchema = z.object({
  attempted: z.number().nullish(),
  resilient: z.number().nullish(),
  vulnerable: z.number().nullish(),
  skipped: z.number().nullish(),
  errored: z.number().nullish(),
  // Stage-1 — UNCLASSIFIED bucket per exploit target. Tests with no
  // Resolver/Generator attestation stamp count here, not in resilient.
  unclassified: z.number().nullish(),
});

export const SecurityPostureSchema = z.object({
  attempted: z.number().nullish(),
  resilient: z.number().nullish(),
  vulnerable: z.number().nullish(),
  skipped: z.number().nullish(),
  errored: z.number().nullish(),
  // Stage-1 — UNCLASSIFIED count. EXCLUDED from resilience_pct denominator
  // so weakly-tagged runs cannot fake green; surfaced in its own bucket
  // so the dashboard can flag the tagging gap.
  unclassified: z.number().nullish(),
  resilience_pct: z.number().nullish(),
  by_exploit_target: z.record(z.string(), ExploitTargetCountsSchema).nullish(),
});

export const ProjectStateSchema = z
  .object({
    story_id: z.string().nullish(),
    story_title: z.string().nullish(),
    pipeline_mode: PipelineModeSchema,
    run_validity: RunValiditySchema,
    coverage_quality: SuiteQualitySchema.nullish(),
    suite_quality: SuiteQualitySchema.nullish(),
    attestation_banner: z.string().nullish(),
    surface_map: z.record(z.string(), SurfaceBindingSchema).optional(),
    test_suite: z.array(TestCaseSchema).optional(),
    execution_logs: z.array(VerdictRecordSchema).optional(),
    design_contracts: z.array(z.record(z.string(), z.unknown())).optional(),
    security_checklist: z.array(z.record(z.string(), z.unknown())).optional(),
    design_summary: DesignSummarySchema.nullish(),
    coverage_gaps: z.array(CoverageGapSchema).nullish(),
    suggested_patches: z.array(SuggestedPatchSchema).optional(),
    security_posture: SecurityPostureSchema.nullish(),
    test_suite_summary: TestSuiteSummarySchema.nullish(),
    resilience_pct: z.number().nullish(),
    drift_report: z.record(z.string(), z.unknown()).nullish(),
    sast_summary: z.record(z.string(), z.unknown()).nullish(),
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
export type TestSuiteSummary = z.infer<typeof TestSuiteSummarySchema>;
export type DesignSummary = z.infer<typeof DesignSummarySchema>;
export type CoverageGap = z.infer<typeof CoverageGapSchema>;
export type SuggestedPatch = z.infer<typeof SuggestedPatchSchema>;
export type SecurityPosture = z.infer<typeof SecurityPostureSchema>;
export type Health = z.infer<typeof HealthSchema>;
export type PipelineMode = z.infer<typeof PipelineModeSchema>;
export type SuiteQuality = z.infer<typeof SuiteQualitySchema>;
export type RunStatus = z.infer<typeof RunStatusSchema>;
export type PhaseName = z.infer<typeof PhaseNameSchema>;
export type RunPhase = z.infer<typeof RunPhaseSchema>;

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
    }
  | {
      type: "heal_cycle_started";
      run_id: string;
      seq: number;
      ts: string;
      attempt: number;
      failing_test_ids: string[];
    }
  | {
      type: "heal_cycle_completed";
      run_id: string;
      seq: number;
      ts: string;
      attempt: number;
      patches_proposed: number;
    };
