import { toast } from "sonner";
import { Download, FileSpreadsheet, Loader2 } from "lucide-react";
import { useArtifact, useRun } from "@/api/hooks";
import { isReportReady, isRunInFlight } from "@/api/runLifecycle";
import { isPreCode } from "@/api/types";
import { apiFetch } from "@/api/client";
import { buildOwaspChartData, OwaspBarChart } from "@/components/charts/OwaspBarChart";
import { ResilienceGauge } from "@/components/charts/ResilienceGauge";
import { SuiteQualityBadge } from "@/components/SuiteQualityBadge";
import { RunValidityHero } from "@/components/report/RunValidityHero";
import { TechniquePanel } from "@/components/report/TechniquePanel";
import { FindingsTable } from "@/components/report/FindingsTable";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ReportTabProps {
  runId?: string;
  storyTitle?: string;
}

export function ReportTab({ runId, storyTitle }: ReportTabProps) {
  const { data: run } = useRun(runId);
  const reportReady = isReportReady(run?.status);
  const { data: artifact, isLoading, isError, error } = useArtifact(runId, Boolean(runId) && reportReady);

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
  const sast = artifact.sast_summary as Record<string, unknown> | undefined;
  const totals = (artifact.test_suite_summary as { totals?: { planned?: number; executed?: number } })?.totals;

  async function exportFile(format: "pdf" | "xlsx") {
    try {
      await apiFetch(`/api/runs/${runId}/export?format=${format}`);
      toast.success(`Export ${format.toUpperCase()} requested`);
    } catch {
      toast.error("Export failed — backend export worker may be unavailable.");
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

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Quality gate</CardTitle></CardHeader>
          <CardContent>
            <SuiteQualityBadge quality={quality ?? undefined} />
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

        <Card>
          <CardHeader><CardTitle>Coverage</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-sm">
            <p>{totals?.planned ?? artifact.test_suite?.length ?? 0} tests planned</p>
            <p className="text-muted">{totals?.executed ?? artifact.execution_logs?.length ?? 0} executed</p>
            {posture && (
              <p className="text-muted">
                {posture.resilient} resilient · {posture.vulnerable} vulnerable
              </p>
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

      {sast && (
        <Card>
          <CardHeader><CardTitle>SAST summary (Bandit)</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              <Badge variant="medium">Findings: {String(sast.findings_total ?? 0)}</Badge>
              {Object.entries((sast.by_severity as Record<string, number>) ?? {}).map(([sev, n]) => (
                <Badge
                  key={sev}
                  variant={sev === "HIGH" || sev === "MEDIUM" ? "high" : "low"}
                >
                  {sev}: {n}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

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
              <CardHeader><CardTitle>Design contracts</CardTitle></CardHeader>
              <CardContent>
                <pre className="max-h-48 overflow-auto font-mono text-xs">
                  {JSON.stringify(artifact.design_contracts ?? [], null, 2)}
                </pre>
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Security checklist</CardTitle></CardHeader>
              <CardContent>
                <pre className="max-h-48 overflow-auto font-mono text-xs">
                  {JSON.stringify(artifact.security_checklist ?? [], null, 2)}
                </pre>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {artifact.drift_report && (
        <Card>
          <CardHeader><CardTitle>Drift report</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-6 text-sm">
            {Object.entries(
              ((artifact.drift_report as { summary?: Record<string, number> }).summary ?? artifact.drift_report) as Record<string, unknown>,
            ).map(([k, v]) =>
              typeof v === "number" ? (
                <div key={k}>
                  <p className="text-xs uppercase tracking-wide text-muted">{k.replace(/_/g, " ")}</p>
                  <p className="text-lg font-semibold">{v}</p>
                </div>
              ) : null,
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
