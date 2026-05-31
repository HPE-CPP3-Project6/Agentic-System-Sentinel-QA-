import { Copy, Download, FileCode2 } from "lucide-react";
import { toast } from "sonner";
import { useScript } from "@/api/hooks";
import { CodePanel } from "@/components/CodePanel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ScriptsTabProps {
  runId?: string;
  onTabChange: (tab: "run") => void;
}

export function ScriptsTab({ runId, onTabChange }: ScriptsTabProps) {
  const { data: script, isLoading, isError } = useScript(runId, Boolean(runId));

  if (!runId) {
    return <div className="panel p-6 text-muted">No run selected.</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => onTabChange("run")}>Continue to Run</Button>
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
          {isError && (
            <p className="p-4 text-caution">Script not ready — complete Generator/Compiler first.</p>
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
