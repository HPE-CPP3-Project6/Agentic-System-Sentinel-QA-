import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

interface ResilienceGaugeProps {
  pct: number;
}

export function ResilienceGauge({ pct }: ResilienceGaugeProps) {
  const data = [
    { name: "Resilient", value: pct },
    { name: "Gap", value: Math.max(0, 100 - pct) },
  ];
  const color = pct >= 80 ? "#1e7e34" : pct >= 50 ? "#f0ad4e" : "#c82333";

  return (
    <div className="relative h-[180px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={75}
            startAngle={90}
            endAngle={-270}
            stroke="none"
          >
            <Cell fill={color} />
            <Cell fill="var(--border)" />
          </Pie>
          <Tooltip
            contentStyle={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              fontSize: 12,
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold">{pct.toFixed(0)}%</span>
        <span className="text-xs uppercase tracking-wide text-muted">Resilience</span>
      </div>
    </div>
  );
}
