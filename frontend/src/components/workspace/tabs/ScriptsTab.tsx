import { Braces, Code2, Copy, Download, FileCode2, FileJson, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { useAdvanceRun, useArtifact, useRun, useScript } from "@/api/hooks";
import { isRunInFlight, isScriptReady } from "@/api/runLifecycle";
import type { FlowMode } from "@/api/pipelineSettings";
import type { TestCase } from "@/api/types";
import {
  downloadJsScript,
  downloadTestCasesJson,
  downloadTestCasesXml,
} from "@/lib/exportScripts";
import { CiCdSnippet } from "@/components/report/CiCdSnippet";
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
  // test_suite (for JSON/XML/JS manifests) lives on the artifact, available once
  // the run is paused (regular flow) or completed (auto flow).
  const { data: artifact } = useArtifact(runId, Boolean(runId) && scriptReady);
  const tests = artifact?.test_suite ?? [];

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

  const compiling =
    isRunInFlight(run?.status) &&
    (run?.current_phase === "security_compiler" || run?.current_phase === "compiler");

  if (compiling) {
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
    <div className="min-w-0 space-y-4">
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
      <Card className="min-w-0 overflow-hidden">
        <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 normal-case">
          <CardTitle className="flex min-w-0 items-center gap-2 truncate font-mono text-sm">
            <FileCode2 className="h-4 w-4 shrink-0" strokeWidth={1.75} />
            test_sentinel_api_generated.py
          </CardTitle>
          {script && (
            <div className="flex shrink-0 gap-2">
              <CopyButton text={script} />
              <DownloadButton text={script} runId={runId} />
            </div>
          )}
        </CardHeader>
        <CardContent className="min-w-0 p-0">
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
          <div className="space-y-2 border-t border-border p-3">
            <p className="text-xs text-muted">
              <span className="font-medium text-foreground">test_sentinel_api_generated.py</span> is the
              production runner (full harness: auth bootstrap, repeat loops, forbidden-content
              assertions). Below are alternate formats generated from the bound test suite.
            </p>
            <ScriptExportBar tests={tests} runId={runId} />
          </div>
        </CardContent>
      </Card>

      {script && <CiCdSnippet />}
    </div>
  );
}

/** Multi-format export of the generated test cases (req 3): JSON / XML / JS. */
function ScriptExportBar({ tests, runId }: { tests: TestCase[]; runId: string }) {
  const stem = `sentinel_${runId}`;
  const disabled = tests.length === 0;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => {
          downloadTestCasesJson(tests, stem);
          toast.success(`Exported ${tests.length} test cases (JSON)`);
        }}
      >
        <FileJson className="h-3.5 w-3.5" strokeWidth={1.75} />
        JSON
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => {
          downloadTestCasesXml(tests, stem);
          toast.success(`Exported ${tests.length} test cases (XML)`);
        }}
      >
        <Braces className="h-3.5 w-3.5" strokeWidth={1.75} />
        XML
      </Button>
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => {
          downloadJsScript(tests, stem);
          toast.success("Exported runnable JS scaffold (.mjs)");
        }}
      >
        <Code2 className="h-3.5 w-3.5" strokeWidth={1.75} />
        JS scaffold
      </Button>
      {disabled && (
        <span className="text-[11px] text-muted">
          Test suite not loaded yet — available once the run is paused or completed.
        </span>
      )}
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
