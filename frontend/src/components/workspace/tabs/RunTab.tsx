import { useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  Circle,
  Loader2,
  MinusCircle,
  Pause,
  Play,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { useAdvanceRun, useArtifact, useHealth, useRun } from "@/api/hooks";
import { canStartExecution, isReportReady, isRunInFlight } from "@/api/runLifecycle";
import { useRunStreamStore } from "@/stores/runStreamStore";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PatchInbox } from "@/components/PatchInbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatRow, type Stat } from "@/components/ui/StatRow";
import { STATUS_LABELS, VERDICT_LABELS, labelText } from "@/lib/labels";
import type { VerdictRecord } from "@/api/types";

interface RunTabProps {
  runId?: string;
  onTabChange: (tab: "report") => void;
}

const PHASE_LABELS: Record<string, string> = {
  critic: "Critic",
  surface_resolver: "Surface",
  generator: "Generator",
  security_compiler: "Compiler",
  compiler: "Compiler",
  executor: "Executor",
};

export function RunTab({ runId, onTabChange }: RunTabProps) {
  const { data: health } = useHealth();
  const { data: run } = useRun(runId);
  const advance = useAdvanceRun(runId);
  const reportReady = isReportReady(run?.status);
  const { data: artifact } = useArtifact(runId, Boolean(runId) && reportReady);
  const streamPhases = useRunStreamStore((s) => s.phases);
  const logLines = useRunStreamStore((s) => s.logLines);
  const streamVerdicts = useRunStreamStore((s) => s.verdicts);
  const streamStatus = useRunStreamStore((s) => s.runStatus);
  const failureCode = useRunStreamStore((s) => s.failureCode);
  const failureMessage = useRunStreamStore((s) => s.failureMessage);
  const logRef = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);

  const phases = streamPhases.length ? streamPhases : (run?.phases ?? []);
  const runStatus =
    streamStatus !== "idle" ? streamStatus : (run?.status ?? "idle");

  const verdicts: VerdictRecord[] = useMemo(() => {
    if (streamVerdicts.length) return streamVerdicts;
    return artifact?.execution_logs ?? [];
  }, [streamVerdicts, artifact?.execution_logs]);

  useEffect(() => {
    if (!paused && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logLines, paused]);

  // Only jump to Report when execution *just* finished — not when reviewing a completed run.
  const prevRunStatus = useRef(run?.status);
  useEffect(() => {
    const prev = prevRunStatus.current;
    const now = run?.status ?? (runStatus !== "idle" ? runStatus : undefined);
    prevRunStatus.current = now;
    const wasInFlight = prev === "running" || prev === "queued";
    if (wasInFlight && now === "completed") {
      onTabChange("report");
    }
  }, [runStatus, run?.status, onTabChange]);

  if (!runId) {
    return <div className="panel p-6 text-muted">Select a run from Scripts to execute tests.</div>;
  }

  const targetDown = health && !health.target_app_ok;
  const patches = artifact?.suggested_patches ?? [];
  const displayFailure = failureCode ?? (run?.status === "failed" ? run.error_code : null);
  const displayFailureMsg =
    failureMessage ?? (run?.status === "failed" ? run.error_message : null);
  const awaitingExecution = canStartExecution(run?.status, run?.current_phase);

  async function startExecution() {
    await advance.mutateAsync({ stop_after: null });
    toast.success("Execution started");
  }

  if (isRunInFlight(run?.status) || (runStatus === "running" && run?.status !== "completed")) {
    return (
      <div className="space-y-4">
        {targetDown && (
          <ErrorBanner
            code="target_app_unreachable"
            message="Target application is unreachable. Execution is blocked until the app responds."
          />
        )}
        <Card>
          <CardHeader><CardTitle>Executing tests</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-2 text-sm">
              <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
              <span>Running pytest against target app…</span>
              <Badge variant="muted">{run?.status}</Badge>
            </div>
            <div className="flex flex-wrap gap-1">
              {phases.map((p) => (
                <Badge
                  key={p.phase}
                  variant={
                    p.status === "completed" ? "success" :
                    p.status === "failed" ? "danger" :
                    p.status === "running" ? "default" : "muted"
                  }
                  className="gap-1 normal-case"
                >
                  {p.status === "running" && <Play className="h-3 w-3" strokeWidth={1.75} />}
                  {PHASE_LABELS[p.phase] ?? p.phase}
                </Badge>
              ))}
            </div>
            {logLines.length > 0 && (
              <div className="max-h-48 overflow-y-auto bg-console-bg p-3 font-mono text-xs text-console-fg">
                {logLines.map((line, i) => <div key={i}>{line}</div>)}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {targetDown && (
        <ErrorBanner
          code="target_app_unreachable"
          message="Target application is unreachable. Execution is blocked until the app responds."
        />
      )}
      {displayFailure && (
        <ErrorBanner code={displayFailure} message={displayFailureMsg ?? "Run failed"} />
      )}

      {awaitingExecution && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between normal-case">
            <CardTitle>Ready to execute</CardTitle>
            <Button
              onClick={() => void startExecution()}
              disabled={advance.isPending || Boolean(targetDown)}
            >
              <Play className="h-4 w-4" strokeWidth={1.75} />
              Start execution
            </Button>
          </CardHeader>
          <CardContent className="text-sm text-muted">
            Pytest script is compiled. Start execution to run tests against the target app.
          </CardContent>
        </Card>
      )}

      {verdicts.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Execution results</CardTitle></CardHeader>
          <CardContent>
            <StatRow
              stats={[
                { label: "Tests", value: verdicts.length },
                { label: "Passed", value: verdicts.filter((v) => v.status === "passed").length, tone: "text-success" },
                { label: "Failed", value: verdicts.filter((v) => v.status === "failed").length, tone: "text-danger" },
                { label: "Resilient", value: verdicts.filter((v) => v.verdict === "resilient").length, tone: "text-success" },
                {
                  label: "Vulnerable",
                  value: verdicts.filter((v) => v.verdict === "vulnerable").length,
                  tone: verdicts.some((v) => v.verdict === "vulnerable") ? "text-danger" : "text-muted",
                },
              ] satisfies Stat[]}
            />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Build phases</CardTitle></CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-1">
            {phases.map((p) => (
              <Badge
                key={p.phase}
                variant={
                  p.status === "completed" ? "success" :
                  p.status === "failed" ? "danger" :
                  p.status === "running" ? "default" : "muted"
                }
                className="gap-1 normal-case"
              >
                {p.status === "running" && <Play className="h-3 w-3" strokeWidth={1.75} />}
                {PHASE_LABELS[p.phase] ?? p.phase}
                {p.duration_ms != null && ` ${(p.duration_ms / 1000).toFixed(1)}s`}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between normal-case">
          <CardTitle>Console output</CardTitle>
          <Button size="sm" variant="outline" onClick={() => setPaused((p) => !p)}>
            <Pause className="h-3.5 w-3.5" strokeWidth={1.75} />
            {paused ? "Resume scroll" : "Pause scroll"}
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <div
            ref={logRef}
            className="max-h-64 overflow-y-auto bg-console-bg p-3 font-mono text-xs text-console-fg"
          >
            {logLines.length === 0 ? (
              <span className="text-muted">
                {awaitingExecution
                  ? "No pytest output yet — click Start execution above."
                  : "No pytest output yet."}
              </span>
            ) : (
              logLines.map((line, i) => <div key={i}>{line}</div>)
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Test results</CardTitle></CardHeader>
        <CardContent className="p-0">
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-8">S</th>
                <th>Test ID</th>
                <th>Status</th>
                <th>Verdict</th>
                <th>Conf</th>
                <th>ms</th>
              </tr>
            </thead>
            <tbody>
              {verdicts.length === 0 ? (
                <tr><td colSpan={6} className="text-muted">No results yet</td></tr>
              ) : (
                verdicts.map((v) => (
                  <tr key={v.test_id}>
                    <td><StatusIcon status={v.status} /></td>
                    <td className="font-mono text-xs">{v.test_id}</td>
                    <td>{labelText(STATUS_LABELS, v.status)}</td>
                    <td>{labelText(VERDICT_LABELS, v.verdict)}</td>
                    <td>{v.verdict_confidence ?? "—"}</td>
                    <td>{v.duration_ms ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {runId && patches.length > 0 && <PatchInbox runId={runId} patches={patches} />}
    </div>
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "passed") {
    return <CheckCircle2 className="h-4 w-4 text-success" strokeWidth={1.75} aria-label="passed" />;
  }
  if (status === "failed") {
    return <XCircle className="h-4 w-4 text-danger" strokeWidth={1.75} aria-label="failed" />;
  }
  if (status === "skipped") {
    return <MinusCircle className="h-4 w-4 text-muted" strokeWidth={1.75} aria-label="skipped" />;
  }
  return <Circle className="h-4 w-4 text-caution" strokeWidth={1.75} aria-label={status} />;
}
