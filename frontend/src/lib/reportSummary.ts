import type { ProjectState } from "@/api/types";

export interface ReportSummary {
  total: number;
  executed: number;
  passed: number;
  failed: number;
  error: number;
  skipped: number;
  /** passed / executed (functional success rate). */
  successPct: number;
  /** Adversarial resilience (security posture), if a security run. */
  resiliencePct: number | null;
  resilient: number | null;
  vulnerable: number | null;
}

/** Single source of truth for the pass/fail/success rollup — used by the
 *  summary tile and every export so the numbers always match. */
export function computeSummary(a: ProjectState): ReportSummary {
  const logs = a.execution_logs ?? [];
  const total = logs.length;
  const passed = logs.filter((l) => l.status === "passed").length;
  const failed = logs.filter((l) => l.status === "failed").length;
  const error = logs.filter((l) => l.status === "error").length;
  const skipped = logs.filter((l) => l.status === "skipped").length;
  const executed = total - skipped;
  const successPct = executed > 0 ? Math.round((passed / executed) * 100) : 0;
  const posture = a.security_posture;
  return {
    total,
    executed,
    passed,
    failed,
    error,
    skipped,
    successPct,
    resiliencePct: posture?.resilience_pct ?? a.resilience_pct ?? null,
    resilient: posture?.resilient ?? null,
    vulnerable: posture?.vulnerable ?? null,
  };
}
