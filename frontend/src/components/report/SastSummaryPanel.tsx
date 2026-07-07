import { ShieldAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export type SastFinding = {
  test_id?: string;
  test_name?: string;
  severity?: string;
  confidence?: string;
  issue?: string;
  path?: string;
  line?: number | string;
  cwe?: string | number;
};

export type SastSummary = {
  tool?: string;
  ran?: boolean;
  reason?: string;
  findings_total?: number;
  files_scanned?: number;
  target?: string;
  by_severity?: Record<string, number>;
  by_rule?: Record<string, number>;
  top_findings?: SastFinding[];
  note?: string;
};

const SEV_BADGE: Record<string, "high" | "medium" | "low" | "muted"> = {
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
};

function formatLocation(path?: string, line?: number | string) {
  if (!path) return "—";
  const base = path.replace(/\\/g, "/").split("/").slice(-2).join("/");
  return line != null && line !== "" ? `${base}:${line}` : base;
}

function ruleLabel(f: SastFinding) {
  const id = f.test_id ?? "?";
  const name = f.test_name?.replace(/_/g, " ");
  return name ? `${id} · ${name}` : id;
}

export function SastSummaryPanel({ summary }: { summary: SastSummary | null | undefined }) {
  if (!summary) return null;

  const ran = summary.ran === true;
  const findings = summary.top_findings ?? [];
  const total = summary.findings_total ?? 0;
  const byRule = summary.by_rule ?? {};

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-primary" strokeWidth={1.75} />
          SAST summary (Bandit)
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!ran ? (
          <p className="text-sm text-caution">
            Static scan did not run{summary.reason ? `: ${summary.reason}` : "."}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="medium">Findings: {total}</Badge>
              {Object.entries(summary.by_severity ?? {}).map(([sev, n]) => (
                <Badge key={sev} variant={SEV_BADGE[sev] ?? "muted"}>
                  {sev}: {n}
                </Badge>
              ))}
              {typeof summary.files_scanned === "number" && summary.files_scanned > 0 && (
                <span className="text-xs text-muted">
                  {summary.files_scanned} file{summary.files_scanned === 1 ? "" : "s"} scanned
                </span>
              )}
            </div>

            {findings.length > 0 ? (
              <div className="overflow-auto rounded border border-border">
                <table className="w-full text-left text-xs">
                  <thead className="bg-surface-elevated">
                    <tr className="section-label">
                      <th className="px-3 py-2 font-medium">Severity</th>
                      <th className="px-3 py-2 font-medium">Rule</th>
                      <th className="px-3 py-2 font-medium">Location</th>
                      <th className="px-3 py-2 font-medium">Issue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {findings.map((f, i) => (
                      <tr key={`${f.test_id}-${f.path}-${f.line}-${i}`} className="border-t border-border align-top">
                        <td className="px-3 py-2 whitespace-nowrap">
                          <Badge variant={SEV_BADGE[String(f.severity).toUpperCase()] ?? "muted"}>
                            {f.severity ?? "—"}
                          </Badge>
                          {f.confidence && (
                            <p className="mt-1 text-[10px] font-medium text-secondary">{f.confidence} confidence</p>
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <p className="font-mono text-[10px]">{ruleLabel(f)}</p>
                          {f.cwe != null && (
                            <p className="text-[10px] text-muted">CWE-{f.cwe}</p>
                          )}
                        </td>
                        <td className="px-3 py-2 font-mono text-[10px] text-muted">
                          {formatLocation(f.path, f.line)}
                        </td>
                        <td className="px-3 py-2 text-muted">{f.issue ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : total === 0 ? (
              <p className="text-sm text-muted">No Bandit issues reported for this target.</p>
            ) : Object.keys(byRule).length > 0 ? (
              <ul className="space-y-1 text-xs text-muted">
                {Object.entries(byRule).map(([rule, count]) => (
                  <li key={rule}>
                    <span className="font-mono text-foreground">{rule}</span> — {count} occurrence
                    {count === 1 ? "" : "s"}
                  </li>
                ))}
              </ul>
            ) : null}

            {summary.note && (
              <p className="text-[10px] text-muted">{summary.note}</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
