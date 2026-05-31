import { Copy, Download, FileCode2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAdvanceRun, useRun, useScript } from "@/api/hooks";
import { isRunInFlight, isScriptReady } from "@/api/runLifecycle";
import type { FlowMode } from "@/api/pipelineSettings";
import { CodePanel } from "@/components/CodePanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ScriptsTabProps {
  runId?: string;
  flowMode?: FlowMode;
  onTabChange: (tab: "run") => void;
}

export function ScriptsTab({ runId, flowMode = "regular", onTabChange }: ScriptsTabProps) {
  const { data: run } = useRun(runId);
  const advance = useAdvanceRun(runId);
  const scriptReady = isScriptReady(run?.status, run?.current_phase);
  const { data: script, isLoading, isError } = useScript(runId, Boolean(runId) && scriptReady);

  async function continueToRun() {
    if (run?.status === "paused") {
      await advance.mutateAsync({ stop_after: null });
      toast.success("Execution started");
    }
    onTabChange("run");
  }

  if (!runId) {
    return <div className="panel p-6 text-muted">No run selected.</div>;
  }

  if (isRunInFlight(run?.status)) {
    return (
      <div className="panel p-6 space-y-4">
        <div className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin text-primary" strokeWidth={1.75} />
          <span>Compiling pytest script…</span>
          <Badge variant="muted">{run?.status}</Badge>
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

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        {flowMode === "regular" ? (
          <Button
            onClick={() => void continueToRun()}
            disabled={!scriptReady || advance.isPending || isRunInFlight(run?.status)}
          >
            Continue to Run
          </Button>
        ) : (
          <span className="text-xs text-muted">Auto flow — execution starts when compiler completes</span>
        )}
      </div>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between normal-case">
          <CardTitle className="flex items-center gap-2 font-mono text-sm">
            <FileCode2 className="h-4 w-4" strokeWidth={1.75} />
            test_sentinel_api_generated.py
          </CardTitle>
          {script && (
            <div className="flex gap-2">
              <CopyButton text={script} />
              <DownloadButton text={script} runId={runId} />
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && <p className="p-4 text-muted">Loading script…</p>}
          {isError && !script && run?.status === "completed" && (
            <p className="p-4 text-caution">
              Script file missing from run workspace — re-run Generator/Compiler or check shim logs.
            </p>
          )}
          {isError && !script && run?.status !== "completed" && (
            <p className="p-4 text-caution">
              Script not ready — finish Generator and Compiler from Scenarios first.
            </p>
          )}
          {script && <CodePanel code={script} />}
          <p className="border-t border-border p-3 text-xs text-muted">
            Generated pytest harness (Python). JS/XML export is not supported in v1.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        toast.success("Copied to clipboard");
      }}
    >
      <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
      Copy
    </Button>
  );
}

function DownloadButton({ text, runId }: { text: string; runId: string }) {
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={() => {
        const blob = new Blob([text], { type: "text/x-python" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `sentinel_${runId}.py`;
        a.click();
        URL.revokeObjectURL(url);
      }}
    >
      <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
      Download
    </Button>
  );
}
