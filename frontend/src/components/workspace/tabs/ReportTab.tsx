import { toast } from "sonner";
import { Download, FileSpreadsheet, Loader2 } from "lucide-react";
import { useArtifact, useRun } from "@/api/hooks";
import { isArtifactReady, isReportReady, isRunInFlight } from "@/api/runLifecycle";
import { isPreCode } from "@/api/types";
import { buildOwaspChartData, OwaspBarChart } from "@/components/charts/OwaspBarChart";
import { ResilienceGauge } from "@/components/charts/ResilienceGauge";
import { SuiteQualityBadge } from "@/components/SuiteQualityBadge";
import { RunValidityHero } from "@/components/report/RunValidityHero";
import { TechniquePanel } from "@/components/report/TechniquePanel";
import { FindingsTable } from "@/components/report/FindingsTable";
import { SastSummaryPanel } from "@/components/report/SastSummaryPanel";
import { DriftReportPanel, type DriftReport } from "@/components/report/DriftReportPanel";
import { SuggestedPatchesPanel } from "@/components/report/SuggestedPatchesPanel";
import { SummaryTile } from "@/components/report/SummaryTile";
import { exportPdf, exportXlsx } from "@/lib/exportReport";
import { httpMethodChip, owaspChip } from "@/lib/chips";
import { cn } from "@/lib/cn";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ReportTabProps {
  runId?: string;
  storyTitle?: string;
}

export function ReportTab({ runId, storyTitle }: ReportTabProps) {
  const { data: run } = useRun(runId);
  const reportReady = isReportReady(run?.status);
  const { data: artifact, isLoading, isError, error } = useArtifact(runId, Boolean(runId) && isArtifactReady(run?.status));

  if (!runId) {
    return <div className="panel p-6 text-muted">Complete a run to view the report.</div>;
  }

  if (run?.status === "failed") {
    return (
      <ErrorBanner
        code={run.error_code ?? "run_failed"}
        message={run.error_message ?? "Run failed before report could be generated."}
      />
    );
  }

  if (isRunInFlight(run?.status)) {
    return (
      <div className="panel flex items-center gap-2 p-6 text-sm">
        <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
        Run in progress — report will be available when execution completes.
      </div>
    );
  }

  if (!reportReady) {
    return (
      <div className="panel p-6 text-muted">
        Report not ready — finish execution on the Run tab first.
      </div>
    );
  }

  if (isLoading) return <p className="p-4 text-muted">Loading report…</p>;
  if (isError) {
    return (
      <ErrorBanner
        code="response_invalid"
        message="Could not load report data from the API."
        detail={error instanceof Error ? error.message : "Schema mismatch — check browser console."}
      />
    );
  }
  if (!artifact) return <p className="p-4 text-muted">Report not available yet.</p>;

  const preCode = isPreCode(artifact.pipeline_mode);
  const quality = artifact.coverage_quality ?? artifact.suite_quality;
  const posture = artifact.security_posture;
  const resilience =
    posture?.resilience_pct ?? artifact.resilience_pct ?? 0;
  const owaspData = buildOwaspChartData(posture?.by_exploit_target ?? {});
  const sast = artifact.sast_summary;
  const totals = (artifact.test_suite_summary as { totals?: { planned?: number; executed?: number } })?.totals;

  async function exportFile(format: "pdf" | "xlsx") {
    try {
      if (format === "pdf") await exportPdf(artifact!, runId);
      else await exportXlsx(artifact!, runId);
      toast.success(`Exported ${format.toUpperCase()}`);
    } catch (e) {
      toast.error(`Export failed: ${e instanceof Error ? e.message : "unknown error"}`);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Dashboard · {storyTitle ?? "Story"}</h2>
          <p className="text-xs text-muted">
            Run {runId} · {String(artifact.pipeline_mode).toUpperCase()}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void exportFile("pdf")}>
            <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
            Export PDF
          </Button>
          <Button size="sm" variant="outline" onClick={() => void exportFile("xlsx")}>
            <FileSpreadsheet className="h-3.5 w-3.5" strokeWidth={1.75} />
            Export Excel
          </Button>
        </div>
      </div>

      {/* Two-axis attestation hero — the headline trustworthiness signal. */}
      <RunValidityHero artifact={artifact} />

      {/* Execution summary dashboard (total / passed / failed / success%). */}
      {!preCode && <SummaryTile artifact={artifact} />}

      {!preCode && (artifact.suggested_patches?.length ?? 0) > 0 && (
        <SuggestedPatchesPanel
          runId={runId}
          storyTitle={storyTitle}
          patches={artifact.suggested_patches ?? []}
        />
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>{preCode ? "Design quality" : "Quality gate"}</CardTitle></CardHeader>
          <CardContent>
            <SuiteQualityBadge quality={quality ?? undefined} />
            {preCode && (
              <p className="mt-2 text-xs text-muted">
                Based on contract coverage and checklist completeness.
              </p>
            )}
          </CardContent>
        </Card>

        {!preCode && artifact.run_validity === "OK" && (
          <Card>
            <CardHeader><CardTitle>Resilience</CardTitle></CardHeader>
            <CardContent>
              <ResilienceGauge pct={resilience} />
            </CardContent>
          </Card>
        )}

        {preCode && (
          <Card>
            <CardHeader><CardTitle>Contract coverage</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {artifact.design_summary ? (
                <>
                  <div>
                    <span className="text-2xl font-bold">
                      {artifact.design_summary.requirements_with_contract ?? 0}
                    </span>
                    <span className="text-sm text-muted">
                      {" "}/ {artifact.design_summary.requirements_total ?? 0} requirements
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-surface-elevated">
                    <div
                      className="h-full rounded-full bg-green-500 transition-all"
                      style={{
                        width: `${Math.round(
                          ((artifact.design_summary.requirements_with_contract ?? 0) /
                            Math.max(1, artifact.design_summary.requirements_total ?? 1)) * 100,
                        )}%`,
                      }}
                    />
                  </div>
                  <p className="text-xs text-muted">
                    {artifact.design_summary.contracts_total ?? 0} contracts ·{" "}
                    {Object.entries(artifact.design_summary.contracts_by_method ?? {})
                      .map(([m, n]) => `${m} ${n}`)
                      .join(" · ") || "no method breakdown"}
                  </p>
                </>
              ) : (
                <p className="text-sm text-muted">No design summary.</p>
              )}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader><CardTitle>{preCode ? "Checklist depth" : "Coverage"}</CardTitle></CardHeader>
          <CardContent>
            {preCode ? (
              artifact.design_summary ? (
                <div className="space-y-3">
                  <div>
                    <span className="text-2xl font-bold">{artifact.design_summary.checklist_total ?? 0}</span>
                    <span className="text-sm text-muted"> items</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(artifact.design_summary.checklist_by_owasp ?? {}).map(([owasp, count]) => (
                      <span
                        key={owasp}
                        className={cn("rounded px-1.5 py-0.5 font-mono text-[10px] font-bold", owaspChip(owasp))}
                      >
                        {owasp} · {String(count)}
                      </span>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted">No checklist data.</p>
              )
            ) : (
              <div className="space-y-1 text-sm">
                <p>{totals?.planned ?? artifact.test_suite?.length ?? 0} tests planned</p>
                <p className="text-muted">{totals?.executed ?? artifact.execution_logs?.length ?? 0} executed</p>
                {posture && (
                  <p className="text-muted">
                    {posture.resilient} resilient · {posture.vulnerable} vulnerable
                  </p>
                )}
                {posture && (posture.unclassified ?? 0) > 0 && (
                  <p className="font-medium text-amber-600 dark:text-amber-500">
                    {posture.unclassified} unclassified
                    <span className="font-normal text-muted"> · excluded from resilience %</span>
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* ISTQB test-design technique breakdown — both modes when present. */}
      <TechniquePanel summary={artifact.test_suite_summary} />

      {!preCode && owaspData.length > 0 && (
        <Card>
          <CardHeader><CardTitle>OWASP by exploit target</CardTitle></CardHeader>
          <CardContent>
            <OwaspBarChart data={owaspData} />
          </CardContent>
        </Card>
      )}

      {/* Per-test findings (Fortify-style triage grid). */}
      {!preCode && <FindingsTable logs={artifact.execution_logs} />}

      <SastSummaryPanel summary={sast} />

      {preCode && (
        <>
          {artifact.design_summary && (
            <Card>
              <CardHeader><CardTitle>Design summary</CardTitle></CardHeader>
              <CardContent className="flex flex-wrap gap-6 text-sm">
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted">Contracts</p>
                  <p className="text-lg font-semibold">{artifact.design_summary.contracts_total ?? 0}</p>
                  <p className="text-xs text-muted">
                    {Object.entries(artifact.design_summary.contracts_by_method ?? {})
                      .map(([m, n]) => `${m} ${n}`)
                      .join(" · ") || "—"}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted">Requirements covered</p>
                  <p className="text-lg font-semibold">
                    {artifact.design_summary.requirements_with_contract ?? 0}/
                    {artifact.design_summary.requirements_total ?? 0}
                  </p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-wide text-muted">Checklist items</p>
                  <p className="text-lg font-semibold">{artifact.design_summary.checklist_total ?? 0}</p>
                  <p className="text-xs text-muted">
                    {Object.entries(artifact.design_summary.checklist_by_owasp ?? {})
                      .map(([o, n]) => `${o}: ${n}`)
                      .join(" · ") || "—"}
                  </p>
                </div>
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Design contracts ({(artifact.design_contracts ?? []).length})</CardTitle></CardHeader>
              <CardContent>
                <div className="max-h-64 space-y-2 overflow-auto">
                  {(artifact.design_contracts ?? []).length === 0 ? (
                    <p className="text-sm text-muted">No contracts generated.</p>
                  ) : (
                    (artifact.design_contracts ?? []).map((c, i) => {
                      const contract = c as Record<string, unknown>;
                      const raw = String(contract.endpoint ?? contract.path ?? "");
                      const methodMatch = raw.match(/^(GET|POST|PUT|PATCH|DELETE|ANY)\s+/i);
                      const method = methodMatch
                        ? methodMatch[1].toUpperCase()
                        : contract.method
                          ? String(contract.method).toUpperCase()
                          : null;
                      const path = methodMatch ? raw.slice(methodMatch[0].length) : raw;
                      const reqId = contract.requirement_id ? String(contract.requirement_id) : null;
                      const ruleList = Array.isArray(contract.validation_rules)
                        ? (contract.validation_rules as unknown[]).map(String)
                        : [];
                      const rules = ruleList.length
                        ? ruleList.slice(0, 3).join(" · ") +
                          (ruleList.length > 3 ? ` · +${ruleList.length - 3} more` : "")
                        : contract.notes ? String(contract.notes) : null;
                      const methodColor = httpMethodChip(method ?? "ANY");
                      return (
                        <div key={i} className="rounded border border-border p-2 text-xs">
                          <div className="flex items-center gap-2">
                            {method && (
                              <span className={cn("shrink-0 font-mono font-bold text-[10px]", methodColor)}>
                                {method}
                              </span>
                            )}
                            <span className="min-w-0 truncate font-medium text-foreground">{path || `Contract ${i + 1}`}</span>
                            {reqId && <span className="ml-auto shrink-0 text-[10px] text-muted">{reqId}</span>}
                          </div>
                          {rules && <p className="mt-1 text-muted">{rules}</p>}
                        </div>
                      );
                    })
                  )}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Security checklist ({(artifact.security_checklist ?? []).length})</CardTitle></CardHeader>
              <CardContent>
                <div className="max-h-64 space-y-2 overflow-auto">
                  {(artifact.security_checklist ?? []).length === 0 ? (
                    <p className="text-sm text-muted">No checklist items generated.</p>
                  ) : (
                    (artifact.security_checklist ?? []).map((item, i) => {
                      const entry = item as Record<string, unknown>;
                      const owaspId = String(entry.owasp_id ?? entry.owasp_category ?? entry.category ?? "");
                      const reqId = entry.requirement_id ? String(entry.requirement_id) : null;
                      const instruction = entry.instruction ?? entry.requirement ?? entry.control;
                      return (
                        <div key={i} className="rounded border border-border p-2 text-xs">
                          <div className="flex items-center gap-2">
                            {owaspId ? (
                              <span className={cn("shrink-0 font-mono font-bold text-[10px]", owaspChip(owaspId))}>
                                {owaspId}
                              </span>
                            ) : null}
                            {reqId && <span className="ml-auto shrink-0 text-[10px] text-muted">{reqId}</span>}
                          </div>
                          {instruction != null && (
                            <p className="mt-1 text-muted">{String(instruction)}</p>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {artifact.drift_report && (
        <DriftReportPanel drift={artifact.drift_report as DriftReport} />
      )}
    </div>
  );
}
