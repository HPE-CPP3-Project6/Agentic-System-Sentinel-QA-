import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, Save } from "lucide-react";
import { toast } from "sonner";
import { useAdvanceRun, useArtifact, usePatchTestCase, useRun } from "@/api/hooks";
import type { TestCase } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ScenariosTabProps {
  runId?: string;
  onTabChange: (tab: "scripts") => void;
}

export function ScenariosTab({ runId, onTabChange }: ScenariosTabProps) {
  const { data: artifact } = useArtifact(runId, Boolean(runId));
  const { data: run } = useRun(runId);
  const patchTest = usePatchTestCase(runId ?? "");
  const advance = useAdvanceRun(runId);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editStatus, setEditStatus] = useState<Record<string, string>>({});

  const tests =
    artifact?.test_suite ??
    (run?.partial_artifact?.test_suite as TestCase[] | undefined) ??
    [];

  if (!runId) {
    return <div className="panel p-6 text-muted">Complete Surface Map and generate tests first.</div>;
  }

  if (!tests.length) {
    return <div className="panel p-6 text-muted">No test scenarios generated yet.</div>;
  }

  async function saveStatus(tc: TestCase) {
    const val = editStatus[tc.test_id];
    if (!val) return;
    await patchTest.mutateAsync({
      tcId: tc.test_id,
      patch: { expected_status_code: Number(val) },
    });
    toast.success(`${tc.test_id} updated`);
  }

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button onClick={() => void advance.mutateAsync({ stop_after: null }).then(() => onTabChange("scripts"))}>
          Continue to Scripts
        </Button>
      </div>
      <div className="panel overflow-hidden">
        <div className="panel-header">Test scenarios ({tests.length})</div>
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-8" />
                <th>Test ID</th>
                <th>Category</th>
                <th>Technique</th>
                <th>Method</th>
                <th>Path</th>
                <th>Expected</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {tests.map((tc) => (
                <Fragment key={tc.test_id}>
                  <tr>
                    <td>
                      <button type="button" onClick={() => setExpanded((x) => (x === tc.test_id ? null : tc.test_id))}>
                        {expanded === tc.test_id ? (
                          <ChevronDown className="h-4 w-4" strokeWidth={1.75} />
                        ) : (
                          <ChevronRight className="h-4 w-4" strokeWidth={1.75} />
                        )}
                      </button>
                    </td>
                    <td className="font-mono text-xs">{tc.test_id}</td>
                    <td>
                      <Badge variant="outline" className="normal-case">{tc.category ?? "—"}</Badge>
                      {tc.adversarial && <Badge variant="high" className="ml-1">ADV</Badge>}
                    </td>
                    <td className="text-xs">{tc.technique ?? "—"}</td>
                    <td>{tc.method}</td>
                    <td className="max-w-[180px] truncate font-mono text-xs">{tc.path}</td>
                    <td>
                      <Input
                        className="h-7 w-16"
                        defaultValue={String(tc.expected_status_code ?? "")}
                        onChange={(e) => setEditStatus((s) => ({ ...s, [tc.test_id]: e.target.value }))}
                      />
                    </td>
                    <td>
                      <Button size="sm" variant="ghost" onClick={() => void saveStatus(tc)}>
                        <Save className="h-3.5 w-3.5" strokeWidth={1.75} />
                      </Button>
                    </td>
                  </tr>
                  {expanded === tc.test_id && (
                    <tr>
                      <td colSpan={8} className="bg-surface-elevated">
                        <pre className="overflow-x-auto p-3 font-mono text-xs">
                          {JSON.stringify(
                            { input_data: tc.input_data, forbidden: tc.forbidden_response_content },
                            null,
                            2,
                          )}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
