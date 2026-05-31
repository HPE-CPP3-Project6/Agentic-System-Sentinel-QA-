import { Check, X } from "lucide-react";
import { usePatchDecision } from "@/api/hooks";
import type { SuggestedPatch } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface PatchInboxProps {
  runId: string;
  patches: SuggestedPatch[];
}

export function PatchInbox({ runId, patches }: PatchInboxProps) {
  const decide = usePatchDecision(runId);
  const pending = patches.filter((p) => !p.decision || p.decision === "pending");

  if (!pending.length) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Suggested patches ({pending.length})</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 p-0">
        <table className="data-table">
          <thead>
            <tr>
              <th>Test</th>
              <th>Summary</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            {pending.map((patch) => (
              <tr key={patch.patch_id}>
                <td className="font-mono text-xs">{patch.test_id}</td>
                <td>{patch.summary}</td>
                <td>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={decide.isPending}
                      onClick={() =>
                        void decide.mutateAsync({
                          patchId: patch.patch_id,
                          decision: "accept",
                        })
                      }
                    >
                      <Check className="h-3 w-3" strokeWidth={1.75} />
                      Accept
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={decide.isPending}
                      onClick={() =>
                        void decide.mutateAsync({
                          patchId: patch.patch_id,
                          decision: "reject",
                        })
                      }
                    >
                      <X className="h-3 w-3" strokeWidth={1.75} />
                      Reject
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
