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
import { cn } from "@/lib/cn";

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

  const funcCount = tests.filter((t) => !t.adversarial).length;
  const advCount = tests.filter((t) => t.adversarial).length;
  const unclassifiedCount = tests.filter((t) => t.adversarial && !t.attestation_mode).length;

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
        <div className="panel-header flex items-center justify-between">
          <span>Test scenarios ({tests.length})</span>
          <span className="text-[11px] font-normal text-muted">
            {funcCount} functional · {advCount} adversarial
            {unclassifiedCount > 0 && (
              <span className="ml-2 text-amber-600 dark:text-amber-500">{unclassifiedCount} unclassified</span>
            )}
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-8" />
                <th>Test ID</th>
                <th>Category</th>
                <th>Technique</th>
                <th>Equiv. Class</th>
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
                    <td className="whitespace-nowrap font-mono text-xs" title={tc.test_id}>{tc.test_id}</td>
                    <td>
                      <div className="flex flex-wrap items-center gap-1">
                        <Badge variant="outline" className="normal-case">{tc.category ?? "—"}</Badge>
                        {tc.adversarial && <Badge variant="high">ADV</Badge>}
                        {tc.adversarial && !tc.attestation_mode && (
                          <Badge variant="caution" className="text-amber-600 dark:text-amber-500 border-amber-500/40 bg-amber-500/10 normal-case">
                            UNCLASSIFIED
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="text-xs">
                      <div className="max-w-[140px] truncate" title={tc.technique ?? undefined}>
                        {tc.technique ? tc.technique.replace(/_/g, " ") : "—"}
                      </div>
                    </td>
                    <td className="text-xs text-muted">
                      <div className="max-w-[120px] truncate" title={tc.equivalence_class ?? undefined}>
                        {tc.equivalence_class ?? "—"}
                      </div>
                    </td>
                    <td className="whitespace-nowrap">{tc.method}</td>
                    <td className="font-mono text-xs">
                      <div className="max-w-[180px] truncate" title={tc.path ?? undefined}>{tc.path}</div>
                    </td>
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
                      <td
                        colSpan={9}
                        className={cn(
                          "border-b border-border bg-surface-elevated border-l-2",
                          tc.adversarial ? "border-l-amber-500" : "border-l-primary/50",
                        )}
                      >
                        <div className="p-4 space-y-3 text-xs">
                          {tc.title && (
                            <p className="border-b border-border/50 pb-2 font-medium text-foreground">
                              {tc.title}
                            </p>
                          )}
                          <div className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
                            {/* Request body */}
                            <div>
                              <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-primary/70">
                                <span className="h-px w-3 bg-primary/40" />
                                Request body
                              </p>
                              {tc.input_data == null || (typeof tc.input_data === "object" && !Array.isArray(tc.input_data) && Object.keys(tc.input_data).length === 0) ? (
                                <p className="italic text-muted">No request body</p>
                              ) : Array.isArray(tc.input_data) ? (
                                <ul className="space-y-0.5">
                                  {(tc.input_data as unknown[]).map((v, i) => (
                                    <li key={i} className="font-mono text-foreground">{String(v)}</li>
                                  ))}
                                </ul>
                              ) : (
                                <div className="space-y-1.5">
                                  {Object.entries(tc.input_data as Record<string, unknown>).map(([k, v]) => {
                                    const raw = typeof v === "string" ? v : JSON.stringify(v);
                                    const display = raw.length > 72 ? `${raw.slice(0, 69)}…` : raw;
                                    return (
                                      <div key={k} className="flex min-w-0 gap-2">
                                        <span className="shrink-0 font-mono text-primary/70">{k}</span>
                                        <span className="min-w-0 break-all font-mono text-foreground/90" title={raw}>{display}</span>
                                      </div>
                                    );
                                  })}
                                </div>
                              )}
                            </div>

                            {/* Forbidden response content */}
                            {(tc.forbidden_response_content ?? []).length > 0 && (
                              <div>
                                <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-red-400/80">
                                  <span className="h-px w-3 bg-red-400/40" />
                                  Must NOT appear in response
                                </p>
                                <div className="flex flex-wrap gap-1.5">
                                  {(tc.forbidden_response_content ?? []).map((f, i) => (
                                    <span key={i} className="rounded border border-red-500/30 bg-red-500/10 px-2 py-0.5 font-mono text-[10px] text-red-400">
                                      {f}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Required response headers */}
                            {tc.required_response_headers && Object.keys(tc.required_response_headers).length > 0 && (
                              <div>
                                <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-blue-400/80">
                                  <span className="h-px w-3 bg-blue-400/40" />
                                  Required response headers
                                </p>
                                <div className="space-y-1">
                                  {Object.entries(tc.required_response_headers).map(([header, value]) => (
                                    <div key={header} className="flex gap-2">
                                      <span className="shrink-0 font-mono text-blue-400">{header}</span>
                                      <span className="text-muted">{value ?? "(present)"}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* Source requirement refs */}
                            {(tc.source_refs ?? []).length > 0 && (
                              <div>
                                <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
                                  <span className="h-px w-3 bg-border" />
                                  Source requirements
                                </p>
                                <div className="flex flex-wrap gap-1.5">
                                  {(tc.source_refs ?? []).map((ref, i) => (
                                    <span key={i} className="rounded border border-primary/20 bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-primary/80">
                                      {ref}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
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
