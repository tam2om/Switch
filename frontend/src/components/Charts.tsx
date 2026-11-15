"use client";

import { Area, AreaChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export interface Series {
  key: string;
  label: string;
  color: string;
}

const COLORS = {
  in: "var(--c-info)",
  out: "var(--c-accent)",
  ok: "var(--c-ok)",
  warn: "var(--c-warn)",
  bad: "var(--c-bad)",
  sim: "var(--c-sim)",
};
export const chartColors = COLORS;

function timeTick(v: string, span: number): string {
  const d = new Date(v);
  return span > 2 * 86400_000
    ? d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" })
    : d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** Time series chart. Gaps (null values) are shown as gaps rather than interpolated, so missing data is visible. */
export function TimeChart({
  data,
  series,
  format,
  height = 220,
  area = true,
  domainMax,
}: {
  data: Record<string, unknown>[];
  series: Series[];
  format: (v: number) => string;
  height?: number;
  area?: boolean;
  domainMax?: number;
}) {
  if (!data.length) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
        No samples collected in this period yet.
      </div>
    );
  }
  const t0 = new Date(String(data[0].t)).getTime();
  const t1 = new Date(String(data[data.length - 1].t)).getTime();
  const span = t1 - t0;
  const common = (
    <>
      <CartesianGrid stroke="var(--c-line)" strokeDasharray="3 3" vertical={false} />
      <XAxis dataKey="t" tickFormatter={(v) => timeTick(v, span)} stroke="var(--c-muted)" fontSize={11} minTickGap={40} />
      <YAxis tickFormatter={(v) => format(Number(v))} stroke="var(--c-muted)" fontSize={11} width={72} domain={[0, domainMax ?? "auto"]} />
      <Tooltip
        contentStyle={{ background: "var(--c-panel)", border: "1px solid var(--c-line)", borderRadius: 6, fontSize: 12 }}
        labelFormatter={(v) => new Date(String(v)).toLocaleString("en-GB")}
        formatter={(v, name) => [v === null || v === undefined ? "no data" : format(Number(v)), String(name)]}
      />
      {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
    </>
  );
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer>
        {area ? (
          <AreaChart data={data} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
            {common}
            {series.map((s) => (
              <Area key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} fill={s.color} fillOpacity={0.15} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
            ))}
          </AreaChart>
        ) : (
          <LineChart data={data} margin={{ top: 5, right: 8, bottom: 0, left: 0 }}>
            {common}
            {series.map((s) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} dot={false} strokeWidth={1.5} connectNulls={false} isAnimationActive={false} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

export function RangePicker<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: T[] }) {
  return (
    <div className="flex items-center rounded-md border border-line p-0.5 text-xs" role="group" aria-label="Time range">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          aria-pressed={value === o}
          onClick={() => onChange(o)}
          className={value === o ? "rounded bg-accent px-2 py-1 text-accent-fg" : "rounded px-2 py-1 text-muted hover:text-fg"}
        >
          {o}
        </button>
      ))}
    </div>
  );
}
