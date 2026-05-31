import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Circle,
  MinusCircle,
  Pause,
  Play,
  XCircle,
} from "lucide-react";
import { useArtifact, useHealth } from "@/api/hooks";
import { useRunStreamStore } from "@/stores/runStreamStore";
import { ErrorBanner } from "@/components/ErrorBanner";
import { PatchInbox } from "@/components/PatchInbox";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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
  const { data: artifact } = useArtifact(runId, Boolean(runId));
  const phases = useRunStreamStore((s) => s.phases);
  const logLines = useRunStreamStore((s) => s.logLines);
  const verdicts = useRunStreamStore((s) => s.verdicts);
  const runStatus = useRunStreamStore((s) => s.runStatus);
  const failureCode = useRunStreamStore((s) => s.failureCode);
  const failureMessage = useRunStreamStore((s) => s.failureMessage);
  const logRef = useRef<HTMLDivElement>(null);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (!paused && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logLines, paused]);

  useEffect(() => {
    if (runStatus === "completed") onTabChange("report");
  }, [runStatus, onTabChange]);

  const targetDown = health && !health.target_app_ok;
  const patches = artifact?.suggested_patches ?? [];

  return (
    <div className="space-y-4">
      {targetDown && (
        <ErrorBanner
          code="target_app_unreachable"
          message="Target application is unreachable. Execution is blocked until the app responds."
        />
      )}
      {failureCode && (
        <ErrorBanner code={failureCode} message={failureMessage ?? "Run failed"} />
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
              <span className="text-muted">Waiting for pytest output…</span>
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
                    <td>{v.status}</td>
                    <td>{v.verdict ?? "—"}</td>
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
