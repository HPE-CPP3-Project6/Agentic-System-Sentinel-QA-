import { useEffect, useMemo, useState } from "react";
import { BarChart3, GitBranch, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import {
  useAdvanceRun,
  useArtifact,
  useHealth,
  useRun,
  useSurfaceOverride,
} from "@/api/hooks";
import { canGenerateTests, isArtifactReady, isRunInFlight } from "@/api/runLifecycle";
import type { FlowMode } from "@/api/pipelineSettings";
import type { RunPhase, SurfaceBinding, WorkspaceTab } from "@/api/types";
import { isPreCode } from "@/api/types";
import { isReportReady } from "@/api/runLifecycle";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { cn } from "@/lib/cn";

interface SurfaceMapTabProps {
  runId?: string;
  flowMode?: FlowMode;
  mode?: string;
  onTabChange: (tab: WorkspaceTab) => void;
}

// PRE_CODE runs the same nodes but the Generator emits DESIGN CONTRACTS and the
// Security Compiler emits a CHECKLIST (not a test suite / pytest), and the
// Executor is a no-op (no app to run). So the live progress should read as a
// design pipeline and drop the executor entirely.
const PRE_CODE_PHASE_LABELS: Partial<Record<string, string>> = {
  critic: "critic",
  surface_resolver: "surface resolver",
  generator: "design contracts",
  security_compiler: "security checklist",
};

function progressPhases(
  phases: RunPhase[],
  mode?: string,
): { phase: string; status: string; label: string }[] {
  if (!isPreCode(mode)) {
    return phases.map((p) => ({ ...p, label: p.phase.replace(/_/g, " ") }));
  }
  return phases
    .filter((p) => p.phase !== "executor")
    .map((p) => ({
      ...p,
      label: PRE_CODE_PHASE_LABELS[p.phase] ?? p.phase.replace(/_/g, " "),
    }));
}

function PhaseProgressChips({ phases, mode }: { phases: RunPhase[]; mode?: string }) {
  const rows = progressPhases(phases, mode);
  if (!rows.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {rows.map((p) => (
        <Badge
          key={p.phase}
          variant={
            p.status === "completed" ? "success" :
            p.status === "running" ? "caution" :
            p.status === "failed" ? "danger" : "muted"
          }
          className="normal-case"
        >
          {p.label} · {p.status}
        </Badge>
      ))}
    </div>
  );
}

const STATE_BADGE: Record<string, "success" | "danger" | "caution" | "muted"> = {
  BACKEND_API: "success",
  NOT_IMPLEMENTED: "danger",
  NEEDS_CLARIFICATION: "caution",
  FRONTEND_ONLY: "muted",
  CLIENT_SIDE_ONLY: "muted",
};

type DesignContract = {
  requirement_id?: string;
  endpoint?: string;
  method?: string;
  request_fields?: Record<string, string>;
  response_fields?: Record<string, string>;
  error_codes?: Record<string, string>;
  validation_rules?: string[];
  notes?: string;
};

const DC_METHOD_COLOR: Record<string, string> = {
  GET: "bg-blue-500/15 text-blue-400",
  POST: "bg-green-500/15 text-green-400",
  PUT: "bg-amber-500/15 text-amber-400",
  PATCH: "bg-amber-500/15 text-amber-400",
  DELETE: "bg-red-500/15 text-red-400",
};

function dcMethod(c: DesignContract): string {
  if (c.method) return c.method.toUpperCase();
  const m = (c.endpoint ?? "").match(/^(GET|POST|PUT|PATCH|DELETE|ANY)\s+/i);
  return m ? m[1].toUpperCase() : "";
}

function dcPath(c: DesignContract): string {
  const raw = (c.endpoint ?? "").trim();
  const m = raw.match(/^(?:GET|POST|PUT|PATCH|DELETE|ANY)\s+(.*)/i);
  return m ? m[1] : raw;
}

export function SurfaceMapTab({ runId, flowMode = "regular", mode, onTabChange }: SurfaceMapTabProps) {
  const { data: health } = useHealth();
  const { data: run, isError: runError, error: runFetchError, isLoading: runLoading } = useRun(runId);
  const artifactReady = isArtifactReady(run?.status);
  const { data: artifact } = useArtifact(runId, Boolean(runId) && artifactReady);
  const advance = useAdvanceRun(runId);
  const override = useSurfaceOverride(runId ?? "");
  const [selectedReq, setSelectedReq] = useState<string | null>(null);
  const [overrideState, setOverrideState] = useState("BACKEND_API");
  const [overridePath, setOverridePath] = useState("/tasks/search");
  const [groupFilter, setGroupFilter] = useState<string>("all");

  const surfaceMap =
    artifact?.surface_map ??
    (run?.partial_artifact?.surface_map as Record<string, SurfaceBinding> | undefined);
  const entries = useMemo(
    () => Object.values((surfaceMap ?? {}) as Record<string, SurfaceBinding>),
    [surfaceMap],
  );

  const preCode = isPreCode(mode);

  const contractMap = useMemo(() => {
    const map = new Map<string, DesignContract[]>();
    ((artifact?.design_contracts ?? []) as DesignContract[]).forEach((c) => {
      const rid = c.requirement_id;
      if (!rid) return;
      if (!map.has(rid)) map.set(rid, []);
      map.get(rid)!.push(c);
    });
    return map;
  }, [artifact?.design_contracts]);

  const selected = entries.find((e) => e.req_id === selectedReq) ?? entries[0];

  useEffect(() => {
    if (selected && !selectedReq) setSelectedReq(selected.req_id);
  }, [selected, selectedReq]);

  if (!runId) {
    return (
      <div className="panel p-6 text-muted">
        Start from Input and click Resolve Surface to populate the traceability map.
      </div>
    );
  }

  if (runLoading && !run) {
    return (
      <div className="panel flex items-center gap-2 p-6 text-sm text-muted">
        <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
        Loading run status…
      </div>
    );
  }

  if (runError) {
    const notFound = runFetchError instanceof ApiError && runFetchError.code === "not_found";
    return (
      <ErrorBanner
        code={notFound ? "not_found" : "response_invalid"}
        message={
          notFound
            ? "Run not found — it may have been deleted or the URL is stale."
            : "Could not load run status from the API."
        }
        detail={
          notFound
            ? "Return to Input and click Resolve Surface again, or pick a run from Run history."
            : runFetchError instanceof Error
              ? runFetchError.message
              : "Check the browser console and shim logs."
        }
      />
    );
  }

  const inFlight = isRunInFlight(run?.status);
  if (inFlight && !entries.length) {
    return (
      <div className="panel p-6 space-y-4">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
          <span>Resolving surfaces…</span>
          <Badge variant="muted">{run?.status ?? "queued"}</Badge>
        </div>
        <PhaseProgressChips phases={run?.phases ?? []} mode={mode} />
        <p className="text-xs text-muted">
          {isPreCode(mode)
            ? "Design-only pipeline — produces design contracts, a security checklist and the surface map (no test execution). Polling every 2s while the LLM runs."
            : "Progress updates via polling every 2s. Critic + surface resolver may take a minute while Chroma and the LLM run."}
        </p>
      </div>
    );
  }

  if (run?.status === "failed") {
    return (
      <ErrorBanner
        code={run.error_code ?? "run_failed"}
        message={run.error_message ?? "Surface resolution failed."}
        detail="Check the shim terminal for errors, then retry from Input."
      />
    );
  }

  if (health && !health.chroma_ok) {
    return (
      <ErrorBanner
        code="chroma_empty"
        message="No code index — Surface Resolver cannot ground requirements."
        detail="Re-index Chroma via Backend/database/ingest.py before resolving."
      />
    );
  }

  if (!entries.length) {
    return (
      <div className="panel p-6 space-y-2 text-muted">
        <p className="font-semibold text-foreground">No surfaces resolved</p>
        <p>Every requirement is NOT_IMPLEMENTED or NEEDS_CLARIFICATION. Override bindings before generating tests.</p>
      </div>
    );
  }

  const severityCounts = entries.reduce(
    (acc, e) => {
      acc[e.state] = (acc[e.state] ?? 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  async function generateTests() {
    await advance.mutateAsync({ stop_after: "compiler" });
    onTabChange("scenarios");
    toast.success("Test generation queued");
  }

  async function applyOverride() {
    if (!selected) return;
    if (run?.status !== "paused") {
      toast.error("Overrides apply only while the run is paused");
      return;
    }
    try {
      await override.mutateAsync({
        [selected.req_id]: {
          state: overrideState,
          backend_endpoints: [{ method: "GET", path: overridePath }],
        },
      });
      toast.success("Override applied for this run");
    } catch {
      toast.error("Could not apply override");
    }
  }

  const filtered =
    groupFilter === "all"
      ? entries
      : entries.filter((e) => e.state === groupFilter);

  const reportReady = isReportReady(run?.status);

  return (
    <div className="space-y-3">
      {inFlight && (
        <div className="panel space-y-3 p-4">
          <div className="flex items-center gap-2 text-sm">
            {preCode ? (
              <span>Building design artifact…</span>
            ) : (
              <span>Pipeline running…</span>
            )}
            <Badge variant="muted">{run?.status ?? "queued"}</Badge>
          </div>
          <PhaseProgressChips phases={run?.phases ?? []} mode={mode} />
        </div>
      )}

      {reportReady && (
        <div className="panel flex flex-wrap items-center justify-between gap-3 border border-primary/40 bg-primary/5 p-4">
          <div>
            <p className="text-sm font-semibold text-foreground">
              {preCode ? "Design pipeline complete" : "Run complete"}
            </p>
            <p className="text-xs text-muted">
              {preCode
                ? "Surface map, design contracts, and security checklist are in the Report tab."
                : "Open Report for attestation, test results, and security posture."}
            </p>
          </div>
          <Button size="sm" onClick={() => onTabChange("report")}>
            <BarChart3 className="h-3.5 w-3.5" strokeWidth={1.75} />
            {preCode ? "View design report" : "View report"}
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-primary" strokeWidth={1.75} />
          <span className="text-sm font-semibold">Surface Map</span>
          {Object.entries(severityCounts).map(([state, n]) => (
            <Badge key={state} variant={STATE_BADGE[state] ?? "muted"} className="normal-case">
              {state} {n}
            </Badge>
          ))}
        </div>
        <div className="flex gap-2">
          {flowMode === "regular" && (
            <Button
              size="sm"
              onClick={() => void generateTests()}
              disabled={advance.isPending || !canGenerateTests(run?.status, run?.current_phase)}
            >
              Generate Tests
            </Button>
          )}
          {flowMode === "auto" && (
            <span className="text-xs text-muted self-center">Auto flow — pipeline advances automatically</span>
          )}
        </div>
      </div>

      <div className="grid min-h-[420px] gap-0 border border-border lg:grid-cols-[220px_1fr_260px]">
        <div className="border-b border-border bg-surface-elevated lg:border-b-0 lg:border-r">
          <div className="panel-header">Requirements</div>
          <div className="p-2">
            <Label>Group by</Label>
            <Select className="mb-2 w-full" value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)}>
              <option value="all">All</option>
              <option value="BACKEND_API">BACKEND_API</option>
              <option value="NOT_IMPLEMENTED">NOT_IMPLEMENTED</option>
            </Select>
          </div>
          <ul className="max-h-[360px] overflow-y-auto">
            {filtered.map((entry) => {
              const hasContract = contractMap.has(entry.req_id);
              return (
                <li key={entry.req_id}>
                  <button
                    type="button"
                    onClick={() => setSelectedReq(entry.req_id)}
                    className={cn(
                      "flex w-full items-center justify-between gap-1 border-b border-border px-3 py-2 text-left text-xs hover:bg-surface",
                      selected?.req_id === entry.req_id && "bg-surface border-l-2 border-l-primary",
                    )}
                  >
                    <span className="font-mono">{entry.req_id}</span>
                    <div className="flex items-center gap-1.5">
                      {preCode ? (
                        <span
                          className={cn("h-2 w-2 shrink-0 rounded-full", hasContract ? "bg-green-500" : "bg-amber-500")}
                          title={hasContract ? "contract generated" : "no contract yet"}
                        />
                      ) : (
                        <>
                          {entry.threat_class && (
                            <span className="max-w-[56px] truncate text-[10px] text-muted" title={entry.threat_class}>
                              {entry.threat_class.length > 8 ? `${entry.threat_class.slice(0, 7)}…` : entry.threat_class}
                            </span>
                          )}
                          {entry.attestation_mode === "missing_control" && (
                            <span className="h-2 w-2 shrink-0 rounded-full bg-red-500" title="missing control" />
                          )}
                          {entry.attestation_mode === "defense_confirming" && (
                            <span className="h-2 w-2 shrink-0 rounded-full bg-green-500" title="defense confirming" />
                          )}
                        </>
                      )}
                      <Badge variant={STATE_BADGE[entry.state] ?? "muted"} className="text-[10px]">
                        {preCode && entry.state === "BACKEND_API"
                          ? "API"
                          : entry.state === "NOT_IMPLEMENTED"
                            ? "GAP"
                            : entry.state.slice(0, 4)}
                      </Badge>
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="border-b border-border lg:border-b-0 lg:border-r">
          <div className="panel-header">{preCode ? "Contract detail" : "Binding detail"}</div>
          {selected && (
            <div className="max-h-[420px] overflow-y-auto space-y-3 p-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{selected.req_id}</span>
                <Badge variant={STATE_BADGE[selected.state] ?? "muted"}>{selected.state}</Badge>
                {selected.attestation_mode === "missing_control" && (
                  <Badge variant="caution" className="normal-case">attesting gap</Badge>
                )}
                {selected.attestation_mode === "defense_confirming" && (
                  <Badge variant="success" className="normal-case">verifying defense</Badge>
                )}
              </div>
              <p className="text-sm">{selected.requirement_text}</p>
              {selected.threat_class && (
                <table className="w-full text-xs">
                  <tbody>
                    <tr><td className="py-1 pr-4 text-muted">Threat</td><td>{selected.threat_class}</td></tr>
                    {selected.defense_kind && (
                      <tr><td className="py-1 pr-4 text-muted">Defense</td><td>{selected.defense_kind}</td></tr>
                    )}
                    <tr><td className="py-1 pr-4 text-muted">Confidence</td><td>{selected.confidence ?? "—"}</td></tr>
                  </tbody>
                </table>
              )}
              {selected.assertion_hint && (
                <div className="border border-border bg-surface-elevated p-2 text-xs">{selected.assertion_hint}</div>
              )}
              {!preCode && selected.backend_endpoints.map((ep, i) => (
                <div key={i} className="border border-border p-2 font-mono text-xs">
                  <span className="text-primary">{ep.method}</span> {ep.path}
                  {ep.handler_file && (
                    <div className="mt-1 text-muted">{ep.handler_file}:{ep.handler_line}</div>
                  )}
                </div>
              ))}
              {selected.grounding_refs.length > 0 && (
                <p className="text-xs text-muted">Grounding: {selected.grounding_refs.join(", ")}</p>
              )}

              {preCode && (
                <div className="space-y-2 border-t border-border pt-3">
                  <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                    Design contracts ({(contractMap.get(selected.req_id) ?? []).length})
                  </p>
                  {(contractMap.get(selected.req_id) ?? []).length === 0 ? (
                    <div className="rounded border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-600 dark:text-amber-500">
                      No design contract generated for this requirement.
                    </div>
                  ) : (
                    (contractMap.get(selected.req_id) ?? []).map((contract, idx) => {
                      const method = dcMethod(contract);
                      const path = dcPath(contract);
                      const reqFields = Object.entries(contract.request_fields ?? {});
                      const respFields = Object.entries(contract.response_fields ?? {});
                      const errorCodes = Object.entries(contract.error_codes ?? {});
                      const rules = contract.validation_rules ?? [];
                      return (
                        <div key={idx} className="overflow-hidden rounded border border-border text-xs">
                          <div className="flex items-center gap-2 bg-surface-elevated px-3 py-2">
                            {method && (
                              <span className={cn("shrink-0 rounded px-1.5 py-0.5 font-mono font-bold text-[10px]", DC_METHOD_COLOR[method] ?? "bg-surface-elevated text-muted")}>
                                {method}
                              </span>
                            )}
                            <span className="truncate font-mono text-foreground">{path || contract.endpoint}</span>
                          </div>
                          <div className="divide-y divide-border">
                            {reqFields.length > 0 && (
                              <div className="px-3 py-2">
                                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Request</p>
                                <div className="space-y-1">
                                  {reqFields.map(([field, type]) => (
                                    <div key={field} className="flex gap-3">
                                      <span className="shrink-0 font-mono text-foreground">{field}</span>
                                      <span className="text-muted">{String(type)}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {respFields.length > 0 && (
                              <div className="px-3 py-2">
                                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Response</p>
                                <div className="space-y-1">
                                  {respFields.map(([field, type]) => (
                                    <div key={field} className="flex gap-3">
                                      <span className="shrink-0 font-mono text-foreground">{field}</span>
                                      <span className="text-muted">{String(type)}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {errorCodes.length > 0 && (
                              <div className="px-3 py-2">
                                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Status codes</p>
                                <div className="space-y-1">
                                  {errorCodes.map(([code, desc]) => (
                                    <div key={code} className="flex gap-3">
                                      <span className={cn("shrink-0 font-mono font-bold", code.startsWith("2") ? "text-green-400" : code.startsWith("4") ? "text-amber-400" : "text-red-400")}>
                                        {code}
                                      </span>
                                      <span className="text-muted">{String(desc)}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                            {rules.length > 0 && (
                              <div className="px-3 py-2">
                                <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted">Validation</p>
                                <ul className="space-y-0.5 text-muted">
                                  {rules.map((rule, i) => (
                                    <li key={i} className="flex gap-1.5">
                                      <span className="shrink-0 text-primary">·</span>
                                      <span>{rule}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            {contract.notes && (
                              <div className="px-3 py-2">
                                <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">Notes</p>
                                <p className="italic text-muted">{contract.notes}</p>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <div>
          <div className="panel-header">Override binding</div>
          <div className="space-y-3 p-4 text-xs">
            <p className="text-muted">
              Applies to this paused run only. Regenerate tests after override.
            </p>
            <div>
              <Label>State</Label>
              <Select value={overrideState} onChange={(e) => setOverrideState(e.target.value)}>
                <option value="BACKEND_API">BACKEND_API</option>
                <option value="NOT_IMPLEMENTED">NOT_IMPLEMENTED</option>
                <option value="NEEDS_CLARIFICATION">NEEDS_CLARIFICATION</option>
              </Select>
            </div>
            <div>
              <Label>Endpoint path</Label>
              <Input value={overridePath} onChange={(e) => setOverridePath(e.target.value)} />
            </div>
            <Button size="sm" variant="secondary" className="w-full" onClick={() => void applyOverride()}>
              Apply override
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
