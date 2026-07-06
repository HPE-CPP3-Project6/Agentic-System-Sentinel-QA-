// Central humanization of backend enums for the reviewer UI.
//
// The pipeline speaks in raw enum tokens (BACKEND_API, DEFENSIVE_INVERTED,
// missing_control, run_validity, …). Rendering those verbatim leaks internal
// vocabulary to reviewers. This module is the single home mapping each enum
// value -> { label, blurb } so screens read as plain language, with the blurb
// available as an on-hover explanation. Free-string values (e.g. an
// unrecognized OWASP target) degrade gracefully through `humanize()`.

export interface LabelMeta {
  /** Human-readable display text. */
  label: string;
  /** One-sentence explanation, surfaced as a tooltip. Empty = no tooltip. */
  blurb: string;
}

/** Title-case fallback for any unmapped value (underscores -> spaces). */
export function humanize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Look up { label, blurb }, falling back to a humanized label with no blurb. */
export function lookupLabel(
  map: Record<string, LabelMeta>,
  value?: string | null,
): LabelMeta {
  if (!value) return { label: "—", blurb: "" };
  return map[value] ?? { label: humanize(value), blurb: "" };
}

/** Convenience: just the display text for a value. */
export function labelText(
  map: Record<string, LabelMeta>,
  value?: string | null,
): string {
  return lookupLabel(map, value).label;
}

// ── Surface Resolver ─────────────────────────────────────────────────────────

export const SURFACE_STATE_LABELS: Record<string, LabelMeta> = {
  BACKEND_API: {
    label: "Backend API",
    blurb: "Bound to a real server endpoint that can be exercised.",
  },
  FRONTEND_ONLY: {
    label: "Frontend only",
    blurb: "Behaviour lives in the UI; there is no backend surface to test.",
  },
  CLIENT_SIDE_ONLY: {
    label: "Client-side only",
    blurb: "Handled entirely in the browser (e.g. a local filter).",
  },
  NOT_IMPLEMENTED: {
    label: "Not implemented",
    blurb: "No matching code was found — the requirement is a gap.",
  },
  NEEDS_CLARIFICATION: {
    label: "Needs clarification",
    blurb: "Ambiguous requirement; it couldn't be bound with confidence.",
  },
};

/** Compact codes for narrow columns; full label lives in the tooltip. */
export const SURFACE_STATE_SHORT: Record<string, string> = {
  BACKEND_API: "API",
  FRONTEND_ONLY: "FE",
  CLIENT_SIDE_ONLY: "CS",
  NOT_IMPLEMENTED: "GAP",
  NEEDS_CLARIFICATION: "N/C",
};

export const THREAT_CLASS_LABELS: Record<string, LabelMeta> = {
  DEFENSIVE_NORMAL: {
    label: "Standard",
    blurb: "Test the feature as specified.",
  },
  DEFENSIVE_INVERTED: {
    label: "Inverted defense",
    blurb:
      "The story describes bad behaviour; we test that the opposite defense holds.",
  },
  NON_FUNCTIONAL: {
    label: "Non-functional",
    blurb: "Cross-cutting concern; often needs clarification.",
  },
};

export const DEFENSE_KIND_LABELS: Record<string, LabelMeta> = {
  INPUT_REJECTION: {
    label: "Input rejection",
    blurb: "Bad input should be rejected with a 4xx.",
  },
  TRANSPORT: {
    label: "Transport",
    blurb: "HTTPS / redirect / transport-security policy.",
  },
  OUTPUT_REDACTION: {
    label: "Output redaction",
    blurb: "Sensitive fields must be absent from the response.",
  },
  IMPLICIT_FILTER: {
    label: "Implicit filter",
    blurb: "Another user's data must not leak (e.g. 404 on IDOR).",
  },
  ERROR_SANITIZATION: {
    label: "Error sanitization",
    blurb: "No stack traces or SQL should appear in error responses.",
  },
};

// ── Attestation / verdicts ───────────────────────────────────────────────────

export const ATTESTATION_MODE_LABELS: Record<string, LabelMeta> = {
  missing_control: {
    label: "Attesting gap",
    blurb:
      "The control is absent — a passing test proves the weakness is real (vulnerable).",
  },
  defense_confirming: {
    label: "Verifying defense",
    blurb:
      "The control exists — a passing test proves it holds (resilient).",
  },
};

export const VERDICT_LABELS: Record<string, LabelMeta> = {
  resilient: {
    label: "Resilient",
    blurb: "The defense held against the adversarial test.",
  },
  vulnerable: {
    label: "Vulnerable",
    blurb: "The test confirmed a real weakness.",
  },
  off_target: {
    label: "Off target",
    blurb: "The test never hit the intended surface — excluded from posture.",
  },
  inconclusive: {
    label: "Inconclusive",
    blurb: "No confident verdict — often an unclassified or defective test.",
  },
  "n/a": {
    label: "N/A",
    blurb: "Not an adversarial test.",
  },
};

export const STATUS_LABELS: Record<string, LabelMeta> = {
  passed: { label: "Passed", blurb: "The pytest assertion passed." },
  failed: { label: "Failed", blurb: "The pytest assertion failed." },
  skipped: { label: "Skipped", blurb: "The test was skipped." },
  error: { label: "Error", blurb: "The test errored before producing a result." },
  off_target: {
    label: "Off target",
    blurb: "The test never reached its intended surface.",
  },
};

// ── Run validity / coverage quality ──────────────────────────────────────────

export const RUN_VALIDITY_LABELS: Record<string, LabelMeta> = {
  OK: {
    label: "Attestable run",
    blurb: "The app was actually exercised; the posture is trustworthy.",
  },
  FUNCTIONALLY_UNRELIABLE: {
    label: "Functionally unreliable",
    blurb: "Most functional failures are test defects — posture suppressed.",
  },
  TARGET_UNREACHABLE: {
    label: "Target unreachable",
    blurb: "The app was down; nothing was actually attested.",
  },
  DESIGN_ONLY: {
    label: "Design artifact (PRE_CODE)",
    blurb:
      "Contracts + checklist generated before code exists; nothing executed.",
  },
  NOT_ATTESTED: {
    label: "Not attested",
    blurb: "No tests ran — dynamic security posture is not trustworthy.",
  },
};

export const COVERAGE_QUALITY_LABELS: Record<string, LabelMeta> = {
  ATTESTABLE: {
    label: "Trusted",
    blurb: "Meaningful coverage — the posture can be trusted.",
  },
  INSUFFICIENT: {
    label: "Caution",
    blurb: "Coverage is below the floor for a confident verdict.",
  },
  PROXY_HEAVY: {
    label: "Degraded",
    blurb: "High off-target rate — many tests missed their surface.",
  },
  INCONCLUSIVE_HEAVY: {
    label: "Unclassified",
    blurb:
      "Many adversarial tests had no attestation stamp; resilience % is partial.",
  },
  NO_RISKS_PREDICTED: {
    label: "Review",
    blurb: "No OWASP exposure was predicted for this story.",
  },
  ALL_SKIPPED: { label: "Inconclusive", blurb: "Every test was skipped." },
  NO_TESTS_GENERATED: { label: "Blocked", blurb: "No tests were generated." },
  NO_REQUIREMENTS: {
    label: "No requirements",
    blurb: "The Critic produced no requirements.",
  },
  DESIGN_COMPLETE: {
    label: "Design ready",
    blurb: "Contracts + checklist are present.",
  },
  DESIGN_INSUFFICIENT: {
    label: "Design gap",
    blurb: "Design artifacts are missing.",
  },
};

// ── Test design taxonomy ─────────────────────────────────────────────────────

export const CATEGORY_LABELS: Record<string, LabelMeta> = {
  positive: { label: "Positive", blurb: "Happy path / expected success." },
  negative: { label: "Negative", blurb: "Validation / controlled failure." },
  boundary: { label: "Boundary", blurb: "Boundary-value limits." },
  state_transition: {
    label: "State transition",
    blurb: "Multi-step workflow.",
  },
  security: { label: "Security", blurb: "Adversarial / OWASP test." },
};

export const TECHNIQUE_LABELS: Record<string, LabelMeta> = {
  equivalence_partition: {
    label: "Equivalence Partitioning",
    blurb: "One representative test per input class.",
  },
  boundary_value: {
    label: "Boundary Value",
    blurb: "Values at or next to a limit.",
  },
  decision_table: {
    label: "Decision Table",
    blurb: "One row of a condition → action table.",
  },
  state_transition: {
    label: "State Transition",
    blurb: "Ordered multi-step workflow.",
  },
  requirements_based: {
    label: "Requirements-Based",
    blurb: "Direct restatement of an acceptance criterion.",
  },
  security_adversarial: {
    label: "Security / Adversarial",
    blurb: "Attack / abuse case.",
  },
};

// Field-name kickers shown in the report hero.
export const FIELD_LABELS: Record<string, LabelMeta> = {
  run_validity: {
    label: "Run validity",
    blurb: "Did we actually exercise the app? Read this first.",
  },
  coverage_quality: {
    label: "Coverage quality",
    blurb: "Was the test suite meaningful? Only trust it when the run is valid.",
  },
};
