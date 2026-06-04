import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface OwaspDatum {
  target: string;
  resilient: number;
  vulnerable: number;
  skipped: number;
  unclassified: number;
}

interface OwaspBarChartProps {
  data: OwaspDatum[];
}

export function OwaspBarChart({ data }: OwaspBarChartProps) {
  if (!data.length) {
    return <p className="text-sm text-muted">No OWASP exploit-target data.</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="target" tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="var(--muted)" />
        <Tooltip
          contentStyle={{
            background: "var(--surface)",
            border: "1px solid var(--border)",
            fontSize: 12,
          }}
        />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="resilient" stackId="a" fill="#1e7e34" name="Resilient" />
        <Bar dataKey="vulnerable" stackId="a" fill="#c82333" name="Vulnerable" />
        <Bar dataKey="skipped" stackId="a" fill="#5c6670" name="Skipped" />
        <Bar dataKey="unclassified" stackId="a" fill="#d97706" name="Unclassified" />
      </BarChart>
    </ResponsiveContainer>
  );
}

type ExploitTargetCounts = {
  resilient?: number | null;
  vulnerable?: number | null;
  skipped?: number | null;
  errored?: number | null;
  unclassified?: number | null;
};

export function buildOwaspChartData(
  byTarget: Record<string, ExploitTargetCounts>,
): OwaspDatum[] {
  return Object.entries(byTarget).map(([target, v]) => ({
    target: target.length > 12 ? `${target.slice(0, 10)}…` : target,
    resilient: v.resilient ?? 0,
    vulnerable: v.vulnerable ?? 0,
    skipped: (v.skipped ?? 0) + (v.errored ?? 0),
    unclassified: v.unclassified ?? 0,
  }));
}
