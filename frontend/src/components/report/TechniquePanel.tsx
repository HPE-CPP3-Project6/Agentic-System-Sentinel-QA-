import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { FlaskConical } from "lucide-react";
import type { TestSuiteSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * ISTQB / ISO 29119-4 test-design technique breakdown — the pipeline's
 * headline QA-maturity differentiator. Renders `by_technique` as a horizontal
 * bar and the equivalence classes covered as chips. Previously this rich data
 * was emitted by the backend but never shown.
 */
const TECHNIQUE_LABELS: Record<string, string> = {
  equivalence_partition: "Equivalence Partitioning",
  boundary_value: "Boundary Value",
  decision_table: "Decision Table",
  state_transition: "State Transition",
  requirements_based: "Requirements-Based",
  security_adversarial: "Security / Adversarial",
};

const TECHNIQUE_COLOR: Record<string, string> = {
  equivalence_partition: "#4f7fff",
  boundary_value: "#7c5cff",
  decision_table: "#00a3a3",
  state_transition: "#0d9488",
  requirements_based: "#6b7280",
  security_adversarial: "#c026d3",
};

export function TechniquePanel({ summary }: { summary?: TestSuiteSummary | null }) {
  const byTech = summary?.by_technique;
  if (!byTech || Object.keys(byTech).length === 0) return null;

  const order = summary?.technique_order ?? Object.keys(byTech);
  const data = order
    .filter((t) => byTech[t])
    .map((t) => ({
      key: t,
      label: TECHNIQUE_LABELS[t] ?? t,
      planned: byTech[t]?.planned ?? 0,
      executed: byTech[t]?.executed ?? 0,
    }))
    .filter((d) => d.planned > 0);

  // Equivalence classes covered (flattened, de-duplicated).
  const eqp = summary?.equivalence_partitions ?? {};
  const classes = Array.from(
    new Set(Object.values(eqp).flatMap((byClass) => Object.keys(byClass))),
  ).sort();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-primary" strokeWidth={1.75} />
          Test-design techniques
          <span className="text-xs font-normal text-muted">ISTQB / ISO 29119-4</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div style={{ height: Math.max(140, data.length * 38) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ left: 8, right: 28, top: 4, bottom: 4 }}>
              <XAxis type="number" hide />
              <YAxis
                type="category"
                dataKey="label"
                width={150}
                tick={{ fontSize: 11, fill: "var(--muted)" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                cursor={{ fill: "var(--surface-elevated)" }}
                contentStyle={{
                  background: "var(--surface-elevated)",
                  border: "1px solid var(--border)",
                  fontSize: 12,
                }}
                formatter={(v) => [`${v} tests`, "planned"]}
              />
              <Bar dataKey="planned" radius={[0, 3, 3, 0]} barSize={18}>
                {data.map((d) => (
                  <Cell key={d.key} fill={TECHNIQUE_COLOR[d.key] ?? "#4f7fff"} />
                ))}
                <LabelList dataKey="planned" position="right" style={{ fontSize: 11, fill: "var(--foreground)" }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {classes.length > 0 && (
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
              Equivalence classes covered ({classes.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {classes.map((c) => (
                <Badge key={c} variant="outline" className="normal-case">
                  {c}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
