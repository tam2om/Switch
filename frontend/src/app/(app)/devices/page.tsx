"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Card, Empty, Input, Loadable, PageHeader, Pagination, Select, SimBadge, Table, Td, Th } from "@/components/ui";
import { fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page } from "@/lib/types";

interface DeviceRow {
  mac: string;
  vlan_id: number | null;
  switch_id: number;
  hostname: string;
  is_simulated: boolean;
  port: string;
  vendor: string | null;
  first_seen: string;
  last_seen: string;
  active: boolean;
  lldp: { system_name: string; remote_port: string } | null;
}

function Devices() {
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const [vlan, setVlan] = useState("");
  const [active, setActive] = useState("true");
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useApi<Page<DeviceRow>>("/devices", { q, vlan_id: vlan, active, page, page_size: 100 });
  return (
    <div>
      <PageHeader title="Connected devices" subtitle="Endpoints learned from switch MAC address tables (uplink ports excluded)" />
      <Card bodyClassName="p-0">
        <div className="flex flex-wrap gap-2 border-b border-line p-3">
          <Input className="w-72" placeholder="MAC address, vendor or switch" aria-label="Search devices" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          <Input className="w-28" type="number" placeholder="VLAN" aria-label="VLAN" value={vlan} onChange={(e) => { setVlan(e.target.value); setPage(1); }} />
          <Select className="w-40" aria-label="Activity" value={active} onChange={(e) => { setActive(e.target.value); setPage(1); }}>
            <option value="true">Currently seen</option>
            <option value="false">No longer seen</option>
            <option value="">All</option>
          </Select>
        </div>
        <Loadable data={data} error={error} retry={() => mutate()}>
          {(d) =>
            d.items.length === 0 ? (
              <Empty>No devices match.</Empty>
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <Th>MAC address</Th>
                      <Th>Vendor</Th>
                      <Th>Switch</Th>
                      <Th>Port</Th>
                      <Th>VLAN</Th>
                      <Th>LLDP</Th>
                      <Th>First seen</Th>
                      <Th>Last seen</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((m) => (
                      <tr key={`${m.mac}-${m.switch_id}-${m.vlan_id}`}>
                        <Td className="font-mono">{m.mac}</Td>
                        <Td>{m.vendor || <span className="text-muted">unknown</span>}</Td>
                        <Td><Link href={`/switches/${m.switch_id}`} className="hover:text-accent">{m.hostname}</Link> <SimBadge show={m.is_simulated} /></Td>
                        <Td><Link href={`/switches/${m.switch_id}?tab=ports&port=${encodeURIComponent(m.port)}`} className="hover:text-accent">{m.port}</Link></Td>
                        <Td>{m.vlan_id ?? "–"}</Td>
                        <Td className="text-xs">{m.lldp ? `${m.lldp.system_name} (${m.lldp.remote_port})` : "–"}</Td>
                        <Td className="text-xs">{fmtDate(m.first_seen)}</Td>
                        <Td className="text-xs">{relTime(m.last_seen)} {!m.active && <Badge>gone</Badge>}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pagination page={page} pageSize={100} total={d.total} onPage={setPage} />
              </>
            )
          }
        </Loadable>
      </Card>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Devices />
    </Suspense>
  );
}
