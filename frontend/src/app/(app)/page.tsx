"use client";

import Link from "next/link";
import { useState } from "react";
import { RangePicker, TimeChart, chartColors } from "@/components/Charts";
import { Badge, Card, Empty, Loadable, Meter, PageHeader, RiskBadge, SimBadge, StatTile, StatusBadge, Table, Td, Th } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { fmtBps, fmtNum, fmtPct, fmtUptime, fmtWatts, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface Overview {
  generated_at: string;
  stale_after_seconds: number;
  switches: { total: number; online: number; offline: number; warning: number; unknown: number; simulated: number; with_fresh_metrics: number };
  ports: { total: number; up: number; down: number; admin_down: number; with_errors: number };
  traffic: { in_bps: number | null; out_bps: number | null; at: string | null; available: boolean };
  poe: { budget_w: number; consumed_w: number; available_w: number; switches_reporting: number };
  devices: { connected: number };
  alerts: Record<string, number>;
  top_switches: { id: number; hostname: string; is_simulated: boolean; in_bps: number; out_bps: number }[];
  top_ports: { switch_id: number; hostname: string; is_simulated: boolean; port: string; description: string; in_bps: number; out_bps: number; speed_mbps: number | null }[];
  health: { id: number; hostname: string; status: string; is_simulated: boolean; cpu_pct: number | null; mem_pct: number | null; temperature_c: number | null; uptime_seconds: number | null; metrics_at: string | null; stale: boolean }[];
  recent_events: { id: number; ts: string; severity: string; message: string; switch_id: number | null }[];
  recent_changes: { id: number; title: string; status: string; risk: string; requested_by: string; created_at: string }[];
}

type Range = "1h" | "6h" | "24h" | "7d";

export default function Dashboard() {
  const { mode, can } = useAuth();
  const [range, setRange] = useState<Range>("1h");
  const ov = useApi<Overview>("/dashboard/overview", undefined, { live: true });
  const traffic = useApi<{ points: { t: string; in_bps: number | null; out_bps: number | null }[] }>("/metrics/traffic", { range }, { live: true });

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={ov.data ? `Updated ${relTime(ov.data.generated_at)} · refreshes automatically` : "Network overview"}
      />
      <Loadable data={ov.data} error={ov.error} retry={() => ov.mutate()}>
        {(d) => {
          const alertTotal = Object.values(d.alerts).reduce((a, b) => a + b, 0);
          const poePct = d.poe.budget_w ? (d.poe.consumed_w / d.poe.budget_w) * 100 : null;
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <StatTile
                  label="Switches online"
                  value={`${d.switches.online} / ${d.switches.total}`}
                  tone={d.switches.offline ? "bad" : "ok"}
                  hint={
                    <>
                      {d.switches.offline} offline · {d.switches.warning} warning
                      {d.switches.simulated > 0 && <span className="text-sim"> · {d.switches.simulated} simulated</span>}
                    </>
                  }
                  href="/switches"
                />
                <StatTile label="Ports up" value={`${fmtNum(d.ports.up)} / ${fmtNum(d.ports.total)}`} hint={`${d.ports.with_errors} with errors · ${d.ports.admin_down} disabled`} tone={d.ports.with_errors ? "warn" : undefined} />
                <StatTile
                  label="Traffic"
                  value={d.traffic.available ? fmtBps((d.traffic.in_bps || 0) + (d.traffic.out_bps || 0)) : "unavailable"}
                  hint={d.traffic.available ? `in ${fmtBps(d.traffic.in_bps)} · out ${fmtBps(d.traffic.out_bps)}` : "No recent counter samples"}
                />
                <StatTile label="PoE consumption" value={fmtWatts(d.poe.consumed_w)} hint={`${fmtPct(poePct)} of ${fmtWatts(d.poe.budget_w)} budget`} href="/poe" tone={poePct && poePct > 85 ? "warn" : undefined} />
                <StatTile label="Connected devices" value={fmtNum(d.devices.connected)} hint="Learned MAC addresses" href="/devices" />
                <StatTile
                  label="Active alerts"
                  value={alertTotal}
                  tone={d.alerts.critical ? "bad" : alertTotal ? "warn" : "ok"}
                  hint={`${d.alerts.critical || 0} critical · ${d.alerts.warning || 0} warning`}
                  href="/alerts"
                />
              </div>

              {d.switches.with_fresh_metrics < d.switches.total && (
                <p className="text-xs text-warn">
                  {d.switches.total - d.switches.with_fresh_metrics} switch(es) have no metrics newer than {Math.round(d.stale_after_seconds / 60)} minutes. Their values are shown as stale.
                </p>
              )}

              <Card title="Network traffic (all switches)" actions={<RangePicker value={range} onChange={setRange} options={["1h", "6h", "24h", "7d"]} />}>
                <TimeChart
                  data={traffic.data?.points || []}
                  series={[
                    { key: "in_bps", label: "In", color: chartColors.in },
                    { key: "out_bps", label: "Out", color: chartColors.out },
                  ]}
                  format={fmtBps}
                />
              </Card>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card title="Busiest switches">
                  {d.top_switches.length ? (
                    <Table>
                      <thead>
                        <tr>
                          <Th>Switch</Th>
                          <Th className="text-right">In</Th>
                          <Th className="text-right">Out</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {d.top_switches.map((s) => (
                          <tr key={s.id}>
                            <Td>
                              <Link href={`/switches/${s.id}`} className="hover:text-accent">{s.hostname}</Link> <SimBadge show={s.is_simulated} />
                            </Td>
                            <Td className="tabular text-right">{fmtBps(s.in_bps)}</Td>
                            <Td className="tabular text-right">{fmtBps(s.out_bps)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  ) : (
                    <Empty>No traffic data yet.</Empty>
                  )}
                </Card>
                <Card title="Busiest ports">
                  {d.top_ports.length ? (
                    <Table>
                      <thead>
                        <tr>
                          <Th>Port</Th>
                          <Th className="text-right">In</Th>
                          <Th className="text-right">Out</Th>
                          {mode === "pro" && <Th className="text-right">Utilisation</Th>}
                        </tr>
                      </thead>
                      <tbody>
                        {d.top_ports.map((p) => {
                          const util = p.speed_mbps ? (Math.max(p.in_bps, p.out_bps) / (p.speed_mbps * 1e6)) * 100 : null;
                          return (
                            <tr key={`${p.switch_id}-${p.port}`}>
                              <Td>
                                <Link href={`/switches/${p.switch_id}?tab=ports&port=${encodeURIComponent(p.port)}`} className="hover:text-accent">
                                  {p.hostname} · {p.port}
                                </Link>{" "}
                                <span className="text-muted">{p.description}</span> <SimBadge show={p.is_simulated} />
                              </Td>
                              <Td className="tabular text-right">{fmtBps(p.in_bps)}</Td>
                              <Td className="tabular text-right">{fmtBps(p.out_bps)}</Td>
                              {mode === "pro" && <Td className="tabular text-right">{fmtPct(util)}</Td>}
                            </tr>
                          );
                        })}
                      </tbody>
                    </Table>
                  ) : (
                    <Empty>No traffic data yet.</Empty>
                  )}
                </Card>
              </div>

              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card title="Switch health (highest load first)">
                  <Table>
                    <thead>
                      <tr>
                        <Th>Switch</Th>
                        <Th>Status</Th>
                        <Th>CPU</Th>
                        <Th>Memory</Th>
                        {mode === "pro" && <Th>Temp</Th>}
                        {mode === "pro" && <Th>Uptime</Th>}
                      </tr>
                    </thead>
                    <tbody>
                      {d.health.slice(0, mode === "pro" ? 15 : 8).map((h) => (
                        <tr key={h.id}>
                          <Td>
                            <Link href={`/switches/${h.id}`} className="hover:text-accent">{h.hostname}</Link> <SimBadge show={h.is_simulated} />
                            {h.stale && <Badge tone="warn">stale</Badge>}
                          </Td>
                          <Td>
                            <StatusBadge status={h.status} />
                          </Td>
                          <Td className="w-28">
                            <div className="tabular text-xs">{fmtPct(h.cpu_pct)}</div>
                            <Meter value={h.cpu_pct} />
                          </Td>
                          <Td className="w-28">
                            <div className="tabular text-xs">{fmtPct(h.mem_pct)}</div>
                            <Meter value={h.mem_pct} />
                          </Td>
                          {mode === "pro" && <Td className="tabular">{h.temperature_c === null ? "n/a" : `${h.temperature_c} °C`}</Td>}
                          {mode === "pro" && <Td className="tabular">{fmtUptime(h.uptime_seconds)}</Td>}
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                </Card>
                <div className="space-y-4">
                  <Card title="Recent events" actions={<Link href="/alerts?tab=events" className="text-xs text-accent">All events</Link>}>
                    {d.recent_events.length ? (
                      <ul className="space-y-1.5 text-sm">
                        {d.recent_events.slice(0, 8).map((e) => (
                          <li key={e.id} className="flex items-start gap-2">
                            <StatusBadge status={e.severity} />
                            <span className="flex-1">{e.message}</span>
                            <span className="whitespace-nowrap text-xs text-muted">{relTime(e.ts)}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <Empty>No events.</Empty>
                    )}
                  </Card>
                  {can("job.view") && (
                    <Card title="Recent changes" actions={<Link href="/changes" className="text-xs text-accent">All changes</Link>}>
                      {d.recent_changes.length ? (
                        <ul className="space-y-1.5 text-sm">
                          {d.recent_changes.map((c) => (
                            <li key={c.id} className="flex flex-wrap items-center gap-2">
                              <Link href={`/changes/${c.id}`} className="font-medium hover:text-accent">#{c.id} {c.title}</Link>
                              <StatusBadge status={c.status} />
                              <RiskBadge risk={c.risk} />
                              <span className="ml-auto text-xs text-muted">
                                {c.requested_by} · {relTime(c.created_at)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <Empty>No changes yet.</Empty>
                      )}
                    </Card>
                  )}
                </div>
              </div>
            </div>
          );
        }}
      </Loadable>
    </div>
  );
}
