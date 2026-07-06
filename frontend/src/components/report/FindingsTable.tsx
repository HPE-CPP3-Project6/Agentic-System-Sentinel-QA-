import { useMemo, useState } from "react";
import { ListChecks } from "lucide-react";
import type { VerdictRecord } from "@/api/types";
import {
  ATTESTATION_MODE_LABELS,
  CATEGORY_LABELS,
  STATUS_LABELS,
  TECHNIQUE_LABELS,
  VERDICT_LABELS,
  humanize,
  labelText,
} from "@/lib/labels";
import { EnumBadge } from "@/components/EnumLabel";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/SearchInput";
import { SortHeader } from "@/components/ui/SortHeader";
import { useTableSort, type Accessors } from "@/lib/useTableSort";
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
  off_target: "muted",
};

const VERDICT_BADGE: Record<string, "success" | "danger" | "muted" | "outline"> = {
  resilient: "success",
  vulnerable: "danger",
  off_target: "muted",
  inconclusive: "outline",
  "n/a": "muted",
};

const FINDINGS_SORT: Accessors<VerdictRecord> = {
  test: (r) => r.title ?? r.test_id,
  technique: (r) => r.technique ?? r.category ?? null,
  target: (r) => r.exploit_target ?? null,
  status: (r) => r.status,
  verdict: (r) => r.verdict ?? null,
};

type Filter = "all" | "issues" | "adversarial" | "passed";

export function FindingsTable({ logs }: { logs?: VerdictRecord[] | null }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [search, setSearch] = useState("");
  const rows = logs ?? [];

  const counts = useMemo(() => {
    return {
      all: rows.length,
      issues: rows.filter(
        (r) =>
          r.status === "failed" ||
          r.status === "error" ||
          r.verdict === "vulnerable" ||
          r.status === "off_target",
      ).length,
      adversarial: rows.filter((r) => r.is_adversarial).length,
      passed: rows.filter((r) => r.status === "passed").length,
    };
  }, [rows]);

  const categories = useMemo(() => {
    const cats = new Set<string>();
    rows.forEach((r) => { if (r.category) cats.add(r.category); });
    return Array.from(cats).sort();
  }, [rows]);

  const filtered = useMemo(() => {
    let base: VerdictRecord[];
    switch (filter) {
      case "issues":
        base = rows.filter(
          (r) =>
            r.status === "failed" ||
            r.status === "error" ||
            r.verdict === "vulnerable" ||
            r.status === "off_target",
        );
        break;
      case "adversarial":
        base = rows.filter((r) => r.is_adversarial);
        break;
      case "passed":
        base = rows.filter((r) => r.status === "passed");
        break;
      default:
        base = rows;
    }
    if (categoryFilter !== "all") {
      base = base.filter((r) => r.category === categoryFilter);
    }
    const q = search.trim().toLowerCase();
    if (q) {
      base = base.filter((r) =>
        [r.test_id, r.title, r.technique, r.exploit_target, r.category].some(
          (v) => v && String(v).toLowerCase().includes(q),
        ),
      );
    }
    return base;
  }, [rows, filter, categoryFilter, search]);
  const { sorted, sort, onSort } = useTableSort(filtered, FINDINGS_SORT);

  if (logs === undefined) return null;

  if (rows.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ListChecks className="h-4 w-4 text-primary" strokeWidth={1.75} />
            Findings
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted">
            No execution logs — run the executor phase to see per-test findings.
          </p>
        </CardContent>
      </Card>
    );
  }

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
          Findings ({sorted.length}{sorted.length !== rows.length && ` of ${rows.length}`})
        </CardTitle>
        <div className="flex flex-wrap items-center gap-2">
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
          {categories.length > 0 && (
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="rounded border border-border bg-surface px-1.5 py-0.5 text-xs text-foreground focus:outline-none"
            >
              <option value="all">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>{labelText(CATEGORY_LABELS, c)}</option>
              ))}
            </select>
          )}
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Filter findings…"
            className="w-40"
            ariaLabel="Filter findings"
          />
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="max-h-[460px] overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-surface-elevated text-muted">
              <tr>
                <SortHeader label="Test" sortKey="test" sort={sort} onSort={onSort} className="px-3 py-2 font-medium" />
                <SortHeader label="Technique" sortKey="technique" sort={sort} onSort={onSort} className="px-3 py-2 font-medium" />
                <SortHeader label="Target" sortKey="target" sort={sort} onSort={onSort} className="px-3 py-2 font-medium" />
                <SortHeader label="Status" sortKey="status" sort={sort} onSort={onSort} className="px-3 py-2 font-medium" />
                <SortHeader label="Verdict" sortKey="verdict" sort={sort} onSort={onSort} className="px-3 py-2 font-medium" />
                <th className="px-3 py-2 font-medium">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.test_id} className="border-t border-border align-top hover:bg-surface">
                  <td className="px-3 py-2">
                    <p className="font-medium">{r.title ?? r.test_id}</p>
                    <p className="font-mono text-[10px] text-muted">{r.test_id}</p>
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {r.technique
                      ? labelText(TECHNIQUE_LABELS, r.technique)
                      : r.category
                        ? labelText(CATEGORY_LABELS, r.category)
                        : "—"}
                  </td>
                  <td className="px-3 py-2 text-muted">
                    {r.exploit_target ? humanize(r.exploit_target) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <EnumBadge map={STATUS_LABELS} value={r.status} variant={STATUS_BADGE[r.status] ?? "muted"} />
                  </td>
                  <td className="px-3 py-2">
                    {r.verdict && r.verdict !== "n/a" ? (
                      <div className="space-y-1">
                        <EnumBadge map={VERDICT_LABELS} value={r.verdict} variant={VERDICT_BADGE[r.verdict] ?? "muted"} />
                        {/* Stage-1: per-test attestation chip. The verdict
                            cascade used this stamp as authority, so showing
                            it makes the WHY of the verdict legible. */}
                        {r.attestation_mode && (
                          <p className="text-[10px] text-muted">
                            {labelText(ATTESTATION_MODE_LABELS, r.attestation_mode)}
                          </p>
                        )}
                        {r.is_adversarial && !r.attestation_mode && r.verdict === "inconclusive" && (
                          <p className="text-[10px] text-amber-600 dark:text-amber-500">
                            UNCLASSIFIED — no Resolver/Generator stamp
                          </p>
                        )}
                      </div>
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
