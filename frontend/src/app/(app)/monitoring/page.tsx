"use client";

import { Download } from "lucide-react";
import { useState } from "react";
import { RangePicker, TimeChart, chartColors } from "@/components/Charts";
import { Badge, Card, Empty, Loadable, PageHeader, Select, Table, Tabs, Td, Th } from "@/components/ui";
import { buildUrl } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBps, fmtDate, fmtNum, fmtPct } from "@/lib/format";
import { useApi } from "@/lib/hooks";

type Kind = "availability" | "bandwidth" | "ports";
type Period = "daily" | "weekly" | "monthly";
type Range = "1h" | "6h" | "24h" | "7d" | "30d";

interface Report {
  kind: Kind;
  period: Period;
  generated_at: string;
  columns: string[];
  rows: Record<string, unknown>[];
}

const KIND_INFO: Record<Kind, string> = {
  availability: "Share of availability polls each switch answered.",
  bandwidth: "Average and peak traffic per switch.",
  ports: "Port utilisation and errors, busiest first.",
};

function cell(col: string, v: unknown): React.ReactNode {
  if (v === null || v === undefined) return "–";
  if (typeof v === "boolean") return col === "simulated" ? (v ? <Badge tone="sim">SIMULATED</Badge> : "") : v ? "yes" : "no";
  if (typeof v === "number") {
    if (col.endsWith("_bps")) return fmtBps(v);
    if (col.endsWith("_pct")) return fmtPct(v);
    return fmtNum(v, Number.isInteger(v) ? 0 : 1);
  }
  return String(v);
}

function ReportView() {
  const { can } = useAuth();
  const [kind, setKind] = useState<Kind>("availability");
  const [period, setPeriod] = useState<Period>("daily");
  const { data, error, mutate } = useApi<Report>(`/reports/${kind}`, { period });
  return (
    <Card
      title="Reports"
      bodyClassName="p-0"
      actions={
        <>
          <Select aria-label="Report" className="w-40" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            <option value="availability">Availability</option>
            <option value="bandwidth">Bandwidth</option>
            <option value="ports">Port utilisation</option>
          </Select>
          <Select aria-label="Period" className="w-32" value={period} onChange={(e) => setPeriod(e.target.value as Period)}>
            <option value="daily">Last 24 hours</option>
            <option value="weekly">Last 7 days</option>
            <option value="monthly">Last 30 days</option>
          </Select>
          {can("report.export") && (
            <a
              href={buildUrl(`/reports/${kind}/export`, { period })}
              className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-panel-2 px-3 text-sm hover:bg-line"
              download
            >
              <Download className="h-4 w-4" /> CSV
            </a>
          )}
        </>
      }
    >
      <p className="px-4 pt-3 text-xs text-muted">{KIND_INFO[kind]} {data && `Generated ${fmtDate(data.generated_at)}.`}</p>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(r) =>
          r.rows.length === 0 ? (
            <Empty>No data for this period.</Empty>
          ) : (
            <div className="max-h-[60vh] overflow-auto">
              <Table>
                <thead>
                  <tr>
                    {r.columns.filter((c) => c !== "switch_id").map((c) => (
                      <Th key={c}>{c.replace(/_/g, " ")}</Th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {r.rows.map((row, i) => (
                    <tr key={i}>
                      {r.columns.filter((c) => c !== "switch_id").map((c) => (
                        <Td key={c} className={typeof row[c] === "number" ? "tabular text-xs" : "text-xs"}>{cell(c, row[c])}</Td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )
        }
      </Loadable>
    </Card>
  );
}

function LiveView() {
  const [range, setRange] = useState<Range>("24h");
  const traffic = useApi<{ bucket: string; points: Record<string, unknown>[] }>("/metrics/traffic", { range }, { live: true });
  return (
    <Card title="Total network traffic" actions={<RangePicker value={range} onChange={setRange} options={["1h", "6h", "24h", "7d", "30d"]} />}>
      <TimeChart height={280} data={traffic.data?.points || []} format={fmtBps} series={[{ key: "in_bps", label: "In", color: chartColors.in }, { key: "out_bps", label: "Out", color: chartColors.out }]} />
      <p className="mt-2 text-xs text-muted">Per-switch and per-port history is on each switch&apos;s Monitoring and Ports tabs.</p>
    </Card>
  );
}

export default function MonitoringPage() {
  const { can } = useAuth();
  const [tab, setTab] = useState<"live" | "reports">(can("metrics.view") ? "live" : "reports");
  return (
    <div>
      <PageHeader title="Monitoring & reports" />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "live", label: "Traffic", hidden: !can("metrics.view") },
          { id: "reports", label: "Reports", hidden: !can("report.view") },
        ]}
      />
      {tab === "live" ? <LiveView /> : <ReportView />}
    </div>
  );
}
