import { Suspense, lazy, useState } from "react";
import { Check, ChevronDown, ChevronRight, Copy, Download, FileCode2, Wrench } from "lucide-react";
import { toast } from "sonner";
import type { SuggestedPatch } from "@/api/types";
import { downloadSuggestedPatches } from "@/lib/exportPatches";
import { owaspChip } from "@/lib/chips";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";

// shiki is heavy — only fetch it when a patch with code is actually expanded,
// so opening the Report tab doesn't pay for the highlighter.
const CodePanel = lazy(() =>
  import("@/components/CodePanel").then((m) => ({ default: m.CodePanel })),
);

interface SuggestedPatchesPanelProps {
  runId: string;
  storyTitle?: string;
  patches: SuggestedPatch[];
}

function targetLabel(p: SuggestedPatch): string {
  const t = (p.target_file ?? "").trim();
  if (!t) return "";
  return t.length > 48 ? `…${t.slice(-45)}` : t;
}

function isCodeFix(p: SuggestedPatch): boolean {
  return (p.target_file ?? "").trim().length > 0;
}

export function SuggestedPatchesPanel({ runId, storyTitle, patches }: SuggestedPatchesPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  if (!patches.length) return null;

  const withCode = patches.filter((p) => (p.suggested_fix ?? "").trim().length > 0).length;

  async function copyFix(p: SuggestedPatch) {
    try {
      await navigator.clipboard.writeText((p.suggested_fix ?? "").trim());
      setCopiedId(p.patch_id);
      toast.success("Patch code copied");
      window.setTimeout(() => setCopiedId((id) => (id === p.patch_id ? null : id)), 1500);
    } catch {
      toast.error("Could not copy to clipboard");
    }
  }

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 py-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileCode2 className="h-4 w-4 text-primary" strokeWidth={1.75} />
          Suggested patches
          <Badge variant="outline" className="normal-case">
            {patches.length}
          </Badge>
        </CardTitle>
        <Button
          size="sm"
          variant="outline"
          onClick={() => downloadSuggestedPatches(patches, runId, storyTitle)}
        >
          <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
          Download patch file
        </Button>
      </CardHeader>
      <CardContent className="space-y-2 pb-3 pt-0">
        <p className="text-xs text-muted">
          Healer proposals from this run ({withCode} with code). Patches with a target file change
          application code; the rest are test defects. Accept/reject on the Run tab.
        </p>
        <div className="space-y-2">
          {patches.map((p) => {
            const isOpen = expandedId === p.patch_id;
            const hasFix = (p.suggested_fix ?? "").trim().length > 0;
            const codeFix = isCodeFix(p);
            return (
              <div
                key={p.patch_id}
                className={cn(
                  "overflow-hidden rounded border border-l-[3px] border-border bg-surface-elevated",
                  codeFix ? "border-l-primary" : "border-l-muted",
                )}
              >
                <button
                  type="button"
                  onClick={() => setExpandedId(isOpen ? null : p.patch_id)}
                  className="flex w-full items-start gap-2 p-2.5 text-left transition-colors hover:bg-surface"
                >
                  {isOpen ? (
                    <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted" strokeWidth={1.75} />
                  ) : (
                    <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted" strokeWidth={1.75} />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <span className="font-mono text-[11px] font-semibold text-foreground">
                        {p.patch_id}
                      </span>
                      <span className="font-mono text-[11px] text-muted">{p.test_id}</span>
                      {p.owasp_category && (
                        <span
                          className={cn(
                            "rounded border px-1.5 py-px font-mono text-[10px] font-bold",
                            owaspChip(p.owasp_category),
                          )}
                        >
                          {p.owasp_category}
                        </span>
                      )}
                      {codeFix ? (
                        <span
                          className="inline-flex min-w-0 items-center gap-1 font-mono text-[11px] text-primary"
                          title={p.target_file ?? ""}
                        >
                          <Wrench className="h-3 w-3 shrink-0" strokeWidth={1.75} />
                          <span className="truncate">{targetLabel(p)}</span>
                        </span>
                      ) : (
                        <Badge variant="muted" className="normal-case">
                          test defect — no code change
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-muted">
                      {p.summary}
                    </p>
                  </div>
                </button>

                {isOpen && (
                  <div className="space-y-3 border-t border-border bg-surface px-3 pb-3 pt-2.5">
                    {(p.related_test_ids ?? []).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {(p.related_test_ids ?? []).map((tid) => (
                          <span
                            key={tid}
                            className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-primary"
                          >
                            {tid}
                          </span>
                        ))}
                      </div>
                    )}

                    {p.bug_explanation && (
                      <div>
                        <p className="section-label mb-1">Why</p>
                        <p className="text-[11px] leading-relaxed text-foreground/90">
                          {p.bug_explanation}
                        </p>
                      </div>
                    )}

                    {hasFix && (
                      <div>
                        <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
                          <p className="section-label">
                            Suggested fix
                            {p.target_file ? (
                              <span className="ml-1.5 font-mono normal-case tracking-normal text-primary">
                                {p.target_file}
                              </span>
                            ) : null}
                          </p>
                          <Button size="sm" variant="outline" onClick={() => void copyFix(p)}>
                            {copiedId === p.patch_id ? (
                              <Check className="h-3.5 w-3.5 text-success" strokeWidth={1.75} />
                            ) : (
                              <Copy className="h-3.5 w-3.5" strokeWidth={1.75} />
                            )}
                            {copiedId === p.patch_id ? "Copied" : "Copy code"}
                          </Button>
                        </div>
                        <Suspense
                          fallback={
                            <pre className="max-h-96 overflow-auto border border-border bg-console-bg p-3 font-mono text-xs leading-relaxed text-console-fg">
                              {(p.suggested_fix ?? "").trim()}
                            </pre>
                          }
                        >
                          <CodePanel
                            code={(p.suggested_fix ?? "").trim()}
                            lang="python"
                            className="max-h-96"
                          />
                        </Suspense>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
