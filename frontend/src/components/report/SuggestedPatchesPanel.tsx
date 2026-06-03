import { Download, FileCode2 } from "lucide-react";
import type { SuggestedPatch } from "@/api/types";
import { downloadSuggestedPatches } from "@/lib/exportPatches";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

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

export function SuggestedPatchesPanel({ runId, storyTitle, patches }: SuggestedPatchesPanelProps) {
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
        <ul className="max-h-36 space-y-1.5 overflow-y-auto border border-border bg-surface-elevated p-2 text-xs">
          {patches.map((p) => (
            <li key={p.patch_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="font-mono text-[10px] text-muted">{p.patch_id}</span>
              <span className="font-mono text-[10px]">{p.test_id}</span>
              <span className="truncate font-mono text-[10px] text-primary" title={p.target_file ?? ""}>
                {targetLabel(p)}
              </span>
              <span className="min-w-0 flex-1 truncate text-muted" title={p.summary}>
                {p.summary}
              </span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
