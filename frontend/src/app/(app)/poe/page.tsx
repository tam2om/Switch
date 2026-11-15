"use client";

import Link from "next/link";
import { useState } from "react";
import { Badge, Card, Empty, Loadable, Meter, PageHeader, SimBadge, StatTile, StatusBadge, Table, Td, Th } from "@/components/ui";
import { fmtPct, fmtWatts, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

interface PoeOverview {
  budget_w: number | null;
  consumed_w: number | null;
  available_w: number | null;
  switches_reporting: number;
  switches: { switch_id: number; hostname: string; is_simulated: boolean; status: string; budget_w: number | null; consumed_w: number | null; metrics_at: string | null; pct: number | null; delivering: number; faults: number; disabled: number }[];
  faults: { switch_id: number; hostname: string; port: string; fault: string | null }[];
  top_ports: { switch_id: number; hostname: string; port: string; power_w: number; power_class: string | null }[];
}

export default function PoePage() {
  const { data, error, mutate } = useApi<PoeOverview>("/poe/overview", undefined, { live: true });
  const [sort, setSort] = useState<"pct" | "hostname">("pct");
  return (
    <div>
      <PageHeader title="Power over Ethernet" subtitle="Budget, consumption and faults across all switches" />
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) => {
          const pct = d.budget_w ? ((d.consumed_w || 0) / d.budget_w) * 100 : null;
          const rows = [...d.switches].sort((a, b) => (sort === "pct" ? (b.pct ?? -1) - (a.pct ?? -1) : a.hostname.localeCompare(b.hostname)));
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatTile label="Consumption" value={fmtWatts(d.consumed_w)} hint={`${fmtPct(pct)} of total budget`} tone={pct && pct > 85 ? "warn" : undefined} />
                <StatTile label="Total budget" value={fmtWatts(d.budget_w)} hint={`${d.switches_reporting} switch(es) reporting`} />
                <StatTile label="Available" value={fmtWatts(d.available_w)} />
                <StatTile label="PoE faults" value={d.faults.length} tone={d.faults.length ? "bad" : "ok"} />
              </div>
              <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                <Card title="Active faults">
                  {d.faults.length === 0 ? (
                    <Empty>No PoE faults.</Empty>
                  ) : (
                    <ul className="space-y-1 text-sm">
                      {d.faults.map((f) => (
                        <li key={`${f.switch_id}-${f.port}`}>
                          <Link href={`/switches/${f.switch_id}?tab=poe`} className="hover:text-accent">{f.hostname} port {f.port}</Link> <Badge tone="bad">{f.fault || "fault"}</Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card title="Highest power ports">
                  {d.top_ports.length === 0 ? (
                    <Empty>No PoE consumption reported.</Empty>
                  ) : (
                    <Table>
                      <tbody>
                        {d.top_ports.map((p) => (
                          <tr key={`${p.switch_id}-${p.port}`}>
                            <Td><Link href={`/switches/${p.switch_id}?tab=poe`} className="hover:text-accent">{p.hostname} · {p.port}</Link></Td>
                            <Td className="text-xs text-muted">class {p.power_class ?? "–"}</Td>
                            <Td className="tabular text-right">{fmtWatts(p.power_w)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </Card>
              </div>
              <Card
                title="Per switch"
                bodyClassName="p-0"
                actions={
                  <select aria-label="Sort" className="h-7 rounded border border-line px-2 text-xs" value={sort} onChange={(e) => setSort(e.target.value as "pct" | "hostname")}>
                    <option value="pct">Sort by utilisation</option>
                    <option value="hostname">Sort by hostname</option>
                  </select>
                }
              >
                <Table>
                  <thead>
                    <tr>
                      <Th>Switch</Th>
                      <Th>Status</Th>
                      <Th className="w-48">Utilisation</Th>
                      <Th className="text-right">Consumed</Th>
                      <Th className="text-right">Budget</Th>
                      <Th className="text-right">Delivering</Th>
                      <Th className="text-right">Faults</Th>
                      <Th className="text-right">Disabled</Th>
                      <Th>Updated</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((s) => (
                      <tr key={s.switch_id}>
                        <Td><Link href={`/switches/${s.switch_id}?tab=poe`} className="hover:text-accent">{s.hostname}</Link> <SimBadge show={s.is_simulated} /></Td>
                        <Td><StatusBadge status={s.status} /></Td>
                        <Td>
                          <div className="tabular text-xs">{fmtPct(s.pct)}</div>
                          <Meter value={s.consumed_w} max={s.budget_w || 0} />
                        </Td>
                        <Td className="tabular text-right">{fmtWatts(s.consumed_w)}</Td>
                        <Td className="tabular text-right">{fmtWatts(s.budget_w)}</Td>
                        <Td className="tabular text-right">{s.delivering}</Td>
                        <Td className={s.faults ? "tabular text-right text-bad" : "tabular text-right"}>{s.faults}</Td>
                        <Td className="tabular text-right">{s.disabled}</Td>
                        <Td className="text-xs text-muted">{relTime(s.metrics_at)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
            </div>
          );
        }}
      </Loadable>
    </div>
  );
}
