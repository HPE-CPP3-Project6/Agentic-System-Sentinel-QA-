import { useState } from "react";
import { ChevronDown, ChevronRight, Download, FileCode2 } from "lucide-react";
import type { SuggestedPatch } from "@/api/types";
import { downloadSuggestedPatches } from "@/lib/exportPatches";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";

interface SuggestedPatchesPanelProps {
  runId: string;
  storyTitle?: string;
  patches: SuggestedPatch[];
}

function targetLabel(p: SuggestedPatch): string {
  const t = (p.target_file ?? "").trim();
  if (!t) return "— (test defect)";
  return t.length > 48 ? `…${t.slice(-45)}` : t;
}

const OWASP_COLOR: Record<string, string> = {
  "A01": "bg-red-500/15 text-red-400 border-red-500/20",
  "A02": "bg-red-500/15 text-red-400 border-red-500/20",
  "A03": "bg-red-500/15 text-red-400 border-red-500/20",
  "A08": "bg-red-500/15 text-red-400 border-red-500/20",
  "A10": "bg-red-500/15 text-red-400 border-red-500/20",
  "A04": "bg-amber-500/15 text-amber-400 border-amber-500/20",
  "A05": "bg-amber-500/15 text-amber-400 border-amber-500/20",
  "A06": "bg-amber-500/15 text-amber-400 border-amber-500/20",
  "A07": "bg-amber-500/15 text-amber-400 border-amber-500/20",
};

function owaspColor(cat?: string | null): string {
  if (!cat) return "bg-surface-elevated text-muted border-border";
  const key = cat.match(/A\d+/)?.[0] ?? "";
  return OWASP_COLOR[key] ?? "bg-blue-500/15 text-blue-400 border-blue-500/20";
}

export function SuggestedPatchesPanel({ runId, storyTitle, patches }: SuggestedPatchesPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  if (!patches.length) return null;

  const withCode = patches.filter((p) => (p.suggested_fix ?? "").trim().length > 0).length;

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
          Healer proposals from this run ({withCode} with code). Full replacement blocks and target
          file paths are in the download — accept/reject on the Run tab.
        </p>
        <div className="space-y-1.5">
          {patches.map((p) => {
            const isOpen = expandedId === p.patch_id;
            const hasFix = (p.suggested_fix ?? "").trim().length > 0;
            return (
              <div key={p.patch_id} className="rounded border border-border bg-surface-elevated text-xs">
                <button
                  type="button"
                  onClick={() => setExpandedId(isOpen ? null : p.patch_id)}
                  className="flex w-full items-start gap-2 p-2 text-left hover:bg-surface"
                >
                  {isOpen ? (
                    <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" strokeWidth={1.75} />
                  ) : (
                    <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" strokeWidth={1.75} />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                      <span className="font-mono text-[10px] text-muted">{p.patch_id}</span>
                      <span className="font-mono text-[10px]">{p.test_id}</span>
                      {p.owasp_category && (
                        <span className={cn("rounded border px-1 py-px font-mono text-[10px] font-bold", owaspColor(p.owasp_category))}>
                          {p.owasp_category}
                        </span>
                      )}
                      <span className="truncate font-mono text-[10px] text-primary" title={p.target_file ?? ""}>
                        {targetLabel(p)}
                      </span>
                    </div>
                    <p className="mt-0.5 truncate text-muted" title={p.summary}>{p.summary}</p>
                  </div>
                </button>
                {isOpen && (
                  <div className="border-t border-border px-3 pb-3 pt-2 space-y-2">
                    {(p.related_test_ids ?? []).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {(p.related_test_ids ?? []).map((tid) => (
                          <span key={tid} className="rounded bg-primary/10 px-1.5 py-0.5 font-mono text-[10px] text-primary">
                            {tid}
                          </span>
                        ))}
                      </div>
                    )}
                    {p.bug_explanation && (
                      <p className="text-muted leading-relaxed">{p.bug_explanation}</p>
                    )}
                    {hasFix && (
                      <pre className="overflow-x-auto rounded bg-surface p-2 font-mono text-[10px] leading-relaxed border border-border">
                        {p.suggested_fix}
                      </pre>
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
