import { useEffect, useMemo, useState } from "react";
import { GitBranch, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  useAdvanceRun,
  useArtifact,
  useHealth,
  useRun,
  useSurfaceOverride,
} from "@/api/hooks";
import type { SurfaceBinding } from "@/api/types";
import { ErrorBanner } from "@/components/ErrorBanner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { cn } from "@/lib/cn";

interface SurfaceMapTabProps {
  runId?: string;
  onTabChange: (tab: "scenarios") => void;
}

const STATE_BADGE: Record<string, "success" | "danger" | "caution" | "muted"> = {
  BACKEND_API: "success",
  NOT_IMPLEMENTED: "danger",
  NEEDS_CLARIFICATION: "caution",
  FRONTEND_ONLY: "muted",
  CLIENT_SIDE_ONLY: "muted",
};

export function SurfaceMapTab({ runId, onTabChange }: SurfaceMapTabProps) {
  const { data: health } = useHealth();
  const { data: run } = useRun(runId);
  const { data: artifact } = useArtifact(runId, Boolean(runId));
  const advance = useAdvanceRun(runId);
  const override = useSurfaceOverride(runId ?? "");
  const [selectedReq, setSelectedReq] = useState<string | null>(null);
  const [overrideState, setOverrideState] = useState("BACKEND_API");
  const [overridePath, setOverridePath] = useState("/tasks/search");
  const [groupFilter, setGroupFilter] = useState<string>("all");

  const surfaceMap = artifact?.surface_map ?? run?.partial_artifact?.surface_map;
  const entries = useMemo(
    () => Object.values((surfaceMap ?? {}) as Record<string, SurfaceBinding>),
    [surfaceMap],
  );

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
    await override.mutateAsync({
      [selected.req_id]: {
        state: overrideState,
        backend_endpoints: [{ method: "GET", path: overridePath }],
      },
    });
    toast.success("Override applied for this run");
  }

  const filtered =
    groupFilter === "all"
      ? entries
      : entries.filter((e) => e.state === groupFilter);

  return (
    <div className="space-y-3">
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
          <Button size="sm" variant="outline">
            <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.75} />
            Re-resolve
          </Button>
          <Button size="sm" onClick={() => void generateTests()} disabled={advance.isPending}>
            Generate Tests
          </Button>
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
            {filtered.map((entry) => (
              <li key={entry.req_id}>
                <button
                  type="button"
                  onClick={() => setSelectedReq(entry.req_id)}
                  className={cn(
                    "flex w-full items-center justify-between border-b border-border px-3 py-2 text-left text-xs hover:bg-surface",
                    selected?.req_id === entry.req_id && "bg-surface border-l-2 border-l-primary",
                  )}
                >
                  <span className="font-mono">{entry.req_id}</span>
                  <Badge variant={STATE_BADGE[entry.state] ?? "muted"} className="text-[10px]">
                    {entry.state === "NOT_IMPLEMENTED" ? "GAP" : entry.state.slice(0, 4)}
                  </Badge>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="border-b border-border lg:border-b-0 lg:border-r">
          <div className="panel-header">Binding detail</div>
          {selected && (
            <div className="space-y-3 p-4 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono font-semibold">{selected.req_id}</span>
                <Badge variant={STATE_BADGE[selected.state] ?? "muted"}>{selected.state}</Badge>
              </div>
              <p>{selected.requirement_text}</p>
              {selected.threat_class && (
                <table className="w-full text-xs">
                  <tbody>
                    <tr><td className="text-muted py-1 pr-4">Threat</td><td>{selected.threat_class}</td></tr>
                    {selected.defense_kind && (
                      <tr><td className="text-muted py-1 pr-4">Defense</td><td>{selected.defense_kind}</td></tr>
                    )}
                    <tr><td className="text-muted py-1 pr-4">Confidence</td><td>{selected.confidence ?? "—"}</td></tr>
                  </tbody>
                </table>
              )}
              {selected.assertion_hint && (
                <div className="border border-border bg-surface-elevated p-2 text-xs">{selected.assertion_hint}</div>
              )}
              {selected.backend_endpoints.map((ep, i) => (
                <div key={i} className="font-mono text-xs border border-border p-2">
                  <span className="text-primary">{ep.method}</span> {ep.path}
                  {ep.handler_file && (
                    <div className="mt-1 text-muted">{ep.handler_file}:{ep.handler_line}</div>
                  )}
                </div>
              ))}
              {selected.grounding_refs.length > 0 && (
                <p className="text-xs text-muted">Grounding: {selected.grounding_refs.join(", ")}</p>
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
