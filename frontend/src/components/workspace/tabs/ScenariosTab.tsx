import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, Save } from "lucide-react";
import { toast } from "sonner";
import {
  useArtifact,
  usePatchTestCase,
  useRun,
} from "@/api/hooks";
import {
  isRunInFlight,
  isScenariosGateDone,
} from "@/api/runLifecycle";
import type { FlowMode } from "@/api/pipelineSettings";
import type { TestCase } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ScenariosTabProps {
  runId?: string;
  flowMode?: FlowMode;
  onTabChange: (tab: "scripts") => void;
}

export function ScenariosTab({ runId, flowMode = "regular", onTabChange }: ScenariosTabProps) {
  const { data: run } = useRun(runId);
  const scenariosReady = isScenariosGateDone(run?.status, run?.current_phase);
  const { data: artifact, isLoading: artifactLoading } = useArtifact(
    runId,
    Boolean(runId) && scenariosReady,
  );
  const patchTest = usePatchTestCase(runId ?? "");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editStatus, setEditStatus] = useState<Record<string, string>>({});

  const tests =
    artifact?.test_suite ??
    (run?.partial_artifact?.test_suite as TestCase[] | undefined) ??
    [];

  if (!runId) {
    return <div className="panel p-6 text-muted">Complete Surface Map and generate tests first.</div>;
  }

  if (run?.status === "failed") {
    return (
      <ErrorBanner
        code={run.error_code ?? "run_failed"}
        message={run.error_message ?? "Test generation failed."}
      />
    );
  }

  const generating =
    isRunInFlight(run?.status) &&
    (run?.current_phase === "generator" || run?.current_phase === "security_compiler");

  if (generating && !tests.length) {
    return (
      <div className="panel p-6 space-y-4">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
          <span>Generating test scenarios…</span>
          <Badge variant="muted">{run?.status ?? "queued"}</Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {(run?.phases ?? []).map((p) => (
            <Badge
              key={p.phase}
              variant={
                p.status === "completed" ? "success" :
                p.status === "running" ? "caution" : "muted"
              }
              className="normal-case"
            >
              {p.phase.replace(/_/g, " ")} · {p.status}
            </Badge>
          ))}
        </div>
      </div>
    );
  }

  if (artifactLoading && !tests.length) {
    return <div className="panel p-6 text-muted">Loading scenarios…</div>;
  }

  if (!tests.length) {
    return (
      <div className="panel p-6 text-muted">
        No test scenarios yet. Return to Surface Map and click Generate Tests.
      </div>
    );
  }

  async function saveStatus(tc: TestCase) {
    const val = editStatus[tc.test_id];
    if (!val) return;
    await patchTest.mutateAsync({
      tcId: tc.test_id,
      patch: { expected_status_code: Number(val) },
    });
    toast.success(`${tc.test_id} updated`);
  }

  async function continueToScripts() {
    onTabChange("scripts");
  }

  const canEdit = run?.status === "paused";

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        {flowMode === "regular" ? (
          <Button onClick={() => void continueToScripts()} disabled={!scenariosReady || isRunInFlight(run?.status)}>
            Continue to Scripts
          </Button>
        ) : run?.current_phase === "generator" && isRunInFlight(run?.status) ? (
          <span className="text-xs text-muted">Auto flow — generating scenarios, then Scripts</span>
        ) : (
          <span className="text-xs text-muted">Auto flow — opening Scripts when the compiler phase starts</span>
        )}
      </div>
      <div className="panel overflow-hidden">
        <div className="panel-header">Test scenarios ({tests.length})</div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-8" />
                <th>Test ID</th>
                <th>Category</th>
                <th>Technique</th>
                <th>Method</th>
                <th>Path</th>
                <th>Expected</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tests.map((tc) => (
                <Fragment key={tc.test_id}>
                  <tr>
                    <td>
                      <button type="button" onClick={() => setExpanded((x) => (x === tc.test_id ? null : tc.test_id))}>
                        {expanded === tc.test_id ? (
                          <ChevronDown className="h-4 w-4" strokeWidth={1.75} />
                        ) : (
                          <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
                        )}
                      </button>
                    </td>
                    <td className="font-mono text-xs">{tc.test_id}</td>
                    <td>
                      <Badge variant="outline" className="normal-case">{tc.category ?? "—"}</Badge>
                      {tc.adversarial && <Badge variant="high" className="ml-1">ADV</Badge>}
                    </td>
                    <td className="text-xs">{tc.technique ?? "—"}</td>
                    <td>{tc.method}</td>
                    <td className="max-w-[180px] truncate font-mono text-xs">{tc.path}</td>
                    <td>
                      <Input
                        className="h-7 w-16"
                        defaultValue={String(tc.expected_status_code ?? "")}
                        disabled={!canEdit}
                        onChange={(e) => setEditStatus((s) => ({ ...s, [tc.test_id]: e.target.value }))}
                      />
                    </td>
                    <td>
                      <Button size="sm" variant="ghost" disabled={!canEdit} onClick={() => void saveStatus(tc)}>
                        <Save className="h-3.5 w-3.5" strokeWidth={1.75} />
                      </Button>
                    </td>
                  </tr>
                  {expanded === tc.test_id && (
                    <tr>
                      <td colSpan={8} className="bg-surface-elevated">
                        <pre className="overflow-x-auto p-3 font-mono text-xs">
                          {JSON.stringify(
                            { input_data: tc.input_data, forbidden: tc.forbidden_response_content },
                            null,
                            2,
                          )}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
