import { useState } from "react";
import { Check, Copy, Download, Workflow } from "lucide-react";
import { toast } from "sonner";
import { CI_PROVIDERS, ciSnippet, type CiProvider } from "@/lib/ciSnippets";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";

/**
 * CI/CD integration snippet panel (req 8) — copyable GitHub Actions / Jenkins /
 * GitLab config that runs the generated pytest harness as a pipeline gate.
 */
export function CiCdSnippet() {
  const [provider, setProvider] = useState<CiProvider>("github");
  const [copied, setCopied] = useState(false);
  const meta = CI_PROVIDERS.find((p) => p.id === provider)!;
  const snippet = ciSnippet(provider);

  async function copy() {
    await navigator.clipboard.writeText(snippet);
    setCopied(true);
    toast.success(`${meta.label} config copied`);
    setTimeout(() => setCopied(false), 1500);
  }

  function download() {
    const blob = new Blob([snippet], { type: "text/yaml" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = meta.filename;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${meta.filename}`);
  }

  return (
    <Card className="min-w-0 overflow-hidden">
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2">
          <Workflow className="h-4 w-4" strokeWidth={1.75} />
          CI/CD integration
        </CardTitle>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => void copy()}>
            {copied ? (
              <Check className="h-3.5 w-3.5" strokeWidth={1.75} />
            ) : (
              <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
            )}
            Copy
          </Button>
          <Button size="sm" variant="outline" onClick={download}>
            <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
            {meta.filename}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {CI_PROVIDERS.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => setProvider(p.id)}
              className={cn(
                "rounded border px-2.5 py-1 text-xs transition-colors",
                provider === p.id
                  ? "border-primary bg-primary/10 font-medium text-primary"
                  : "border-border text-muted hover:bg-muted/10",
              )}
            >
              {p.label}
            </button>
          ))}
        </div>
        <pre className="max-h-[40vh] min-w-0 max-w-full overflow-x-auto overflow-y-auto rounded border border-border bg-console-bg p-4 font-mono text-xs whitespace-pre text-console-fg">
          {snippet}
        </pre>
        <p className="text-[11px] text-muted">
          Runs <span className="font-mono">test_sentinel_api_generated.py</span> as a gate. Define{" "}
          <span className="font-mono">SENTINEL_BASE_URL</span> and{" "}
          <span className="font-mono">SENTINEL_TEST_BEARER_TOKEN</span> as masked secrets/credentials
          in your CI environment.
        </p>
      </CardContent>
    </Card>
  );
}
