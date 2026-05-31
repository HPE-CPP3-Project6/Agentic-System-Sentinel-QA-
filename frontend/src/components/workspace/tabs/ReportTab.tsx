import { toast } from "sonner";
import { Download, FileSpreadsheet } from "lucide-react";
import { useArtifact } from "@/api/hooks";
import { isPreCode } from "@/api/types";
import { apiFetch } from "@/api/client";
import { buildOwaspChartData, OwaspBarChart } from "@/components/charts/OwaspBarChart";
import { ResilienceGauge } from "@/components/charts/ResilienceGauge";
import { SuiteQualityBadge } from "@/components/SuiteQualityBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ReportTabProps {
  runId?: string;
  storyTitle?: string;
}

export function ReportTab({ runId, storyTitle }: ReportTabProps) {
  const { data: artifact, isLoading } = useArtifact(runId, Boolean(runId));

  if (!runId) {
    return <div className="panel p-6 text-muted">Complete a run to view the report.</div>;
  }
  if (isLoading) return <p className="p-4 text-muted">Loading report…</p>;
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
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        <div>
          <h2 className="text-base font-semibold">
            Dashboard · {storyTitle ?? "Story"}
          </h2>
          <p className="text-xs text-muted">
            Run {runId} · {String(artifact.pipeline_mode).toUpperCase()} · {artifact.run_validity}
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

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Quality gate</CardTitle></CardHeader>
          <CardContent>
            <SuiteQualityBadge quality={quality} />
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

      {!preCode && owaspData.length > 0 && (
        <Card>
          <CardHeader><CardTitle>OWASP by exploit target</CardTitle></CardHeader>
          <CardContent>
            <OwaspBarChart data={owaspData} />
          </CardContent>
        </Card>
      )}

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
