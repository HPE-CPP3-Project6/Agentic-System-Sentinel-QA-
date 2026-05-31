import { useMemo, useState } from "react";
import { ListChecks } from "lucide-react";
import type { VerdictRecord } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/cn";

/**
 * Per-test findings table (Fortify-style triage grid). Joins the enriched
 * `execution_logs` so a reviewer can see WHICH test produced WHICH verdict and
 * WHY — without opening the pytest workspace. The "1 vulnerable" question is
 * answerable from this table alone.
 */
const STATUS_BADGE: Record<string, "success" | "danger" | "caution" | "muted"> = {
  passed: "success",
  failed: "danger",
  error: "caution",
  skipped: "muted",
};

const VERDICT_BADGE: Record<string, "success" | "danger" | "muted" | "outline"> = {
  resilient: "success",
  vulnerable: "danger",
  off_target: "muted",
  inconclusive: "outline",
  "n/a": "muted",
};

type Filter = "all" | "issues" | "adversarial" | "passed";

export function FindingsTable({ logs }: { logs?: VerdictRecord[] | null }) {
  const [filter, setFilter] = useState<Filter>("all");
  const rows = logs ?? [];

  const counts = useMemo(() => {
    return {
      all: rows.length,
      issues: rows.filter((r) => r.status === "failed" || r.status === "error" || r.verdict === "vulnerable").length,
      adversarial: rows.filter((r) => r.is_adversarial).length,
      passed: rows.filter((r) => r.status === "passed").length,
    };
  }, [rows]);

  const filtered = useMemo(() => {
    switch (filter) {
      case "issues":
        return rows.filter((r) => r.status === "failed" || r.status === "error" || r.verdict === "vulnerable");
      case "adversarial":
        return rows.filter((r) => r.is_adversarial);
      case "passed":
        return rows.filter((r) => r.status === "passed");
      default:
        return rows;
    }
  }, [rows, filter]);

  if (rows.length === 0) return null;

  const tabs: { id: Filter; label: string }[] = [
    { id: "all", label: `All ${counts.all}` },
    { id: "issues", label: `Issues ${counts.issues}` },
    { id: "adversarial", label: `Security ${counts.adversarial}` },
    { id: "passed", label: `Passed ${counts.passed}` },
  ];

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-primary" strokeWidth={1.75} />
          Findings ({filtered.length})
        </CardTitle>
        <div className="flex gap-1">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setFilter(t.id)}
              className={cn(
                "px-2 py-1 text-xs font-medium",
                filter === t.id
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted hover:text-foreground",
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="max-h-[460px] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface-elevated text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Test</th>
                <th className="px-3 py-2 font-medium">Technique</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Verdict</th>
                <th className="px-3 py-2 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.test_id} className="border-t border-border align-top hover:bg-surface">
                  <td className="px-3 py-2">
                    <p className="font-medium">{r.title ?? r.test_id}</p>
                    <p className="font-mono text-[10px] text-muted">{r.test_id}</p>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {r.technique ? r.technique.replace(/_/g, " ") : r.category ?? "—"}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS_BADGE[r.status] ?? "muted"} className="normal-case">
                      {r.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-2">
                    {r.verdict && r.verdict !== "n/a" ? (
                      <Badge variant={VERDICT_BADGE[r.verdict] ?? "muted"} className="normal-case">
                        {r.verdict}
                      </Badge>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {r.stderr_excerpt ? (
                      <code className="block max-w-md truncate font-mono text-[10px]">{r.stderr_excerpt}</code>
                    ) : r.verdict_evidence && r.verdict_evidence.length > 0 ? (
                      <span className="text-[10px]">{r.verdict_evidence.join("; ")}</span>
                    ) : (
                      <span>—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
