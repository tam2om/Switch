"use client";

import { useEffect, useMemo, useState } from "react";
import { RangePicker, TimeChart, chartColors } from "@/components/Charts";
import type { ChangeRequest } from "@/components/ChangeDialog";
import { PortPanel, portState } from "@/components/PortPanel";
import { Badge, Button, Card, Empty, Loadable, Modal, StatusBadge, Table, Td, Th } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { fmtBps, fmtNum, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Port, SwitchDetail } from "@/lib/types";

type Range = "1h" | "6h" | "24h" | "7d" | "30d";

function PortHistory({ sw, port, onClose }: { sw: SwitchDetail; port: Port | null; onClose: () => void }) {
  const [range, setRange] = useState<Range>("6h");
  const { data } = useApi<{ points: Record<string, unknown>[] }>(port ? `/metrics/switches/${sw.id}/ports/${port.if_index}` : null, { range });
  if (!port) return null;
  return (
    <Modal open title={`Port ${port.name}${port.description ? ` – ${port.description}` : ""}`} onClose={onClose} wide>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <StatusBadge status={port.oper_up ? "online" : "offline"} />
          {!port.admin_up && <Badge tone="bad">disabled</Badge>}
          <span className="text-muted">
            {port.port_type} · {port.speed_mbps ? `${port.speed_mbps} Mbps ${port.duplex || ""}` : "no link"} · VLAN {port.untagged_vlan ?? "–"}
            {port.tagged_vlans.length > 0 && ` + tagged ${port.tagged_vlans.join(", ")}`} · {port.flap_count} flap(s)
          </span>
          <span className="ml-auto">
            <RangePicker value={range} onChange={setRange} options={["1h", "6h", "24h", "7d", "30d"]} />
          </span>
        </div>
        <Card title="Traffic">
          <TimeChart data={data?.points || []} format={fmtBps} series={[{ key: "in_bps", label: "In", color: chartColors.in }, { key: "out_bps", label: "Out", color: chartColors.out }]} />
        </Card>
        <Card title="Errors and discards (per interval)">
          <TimeChart
            data={data?.points || []}
            area={false}
            height={160}
            format={(v) => fmtNum(v)}
            series={[
              { key: "in_errors", label: "In errors", color: chartColors.bad },
              { key: "out_errors", label: "Out errors", color: chartColors.warn },
              { key: "in_discards", label: "In discards", color: chartColors.sim },
            ]}
          />
        </Card>
        {(port.macs.length > 0 || port.neighbors.length > 0) && (
          <Card title="Attached">
            <ul className="space-y-1 text-sm">
              {port.neighbors.map((n, i) => (
                <li key={`n${i}`}>
                  LLDP neighbour <strong>{n.system_name}</strong> port {n.remote_port}
                </li>
              ))}
              {port.macs.map((m) => (
                <li key={m.mac} className="font-mono">
                  {m.mac} <span className="font-sans text-muted">VLAN {m.vlan_id ?? "–"} {m.vendor || ""}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </Modal>
  );
}

export function PortsTab({ sw, initialPort, onChange }: { sw: SwitchDetail; initialPort?: string | null; onChange: (r: ChangeRequest) => void }) {
  const { can, mode } = useAuth();
  const { data, error, mutate } = useApi<Port[]>(`/switches/${sw.id}/ports`, undefined, { live: true });
  const [selected, setSelected] = useState<Set<string>>(new Set(initialPort ? [initialPort] : []));
  const [detail, setDetail] = useState<Port | null>(null);
  const [filter, setFilter] = useState<"all" | "up" | "down" | "errors" | "poe">("all");

  useEffect(() => {
    if (initialPort && data) setDetail(data.find((p) => p.name === initialPort) || null);
  }, [initialPort, data]);

  const toggle = (name: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });
  const sel = useMemo(() => (data || []).filter((p) => selected.has(p.name)), [data, selected]);
  const names = sel.map((p) => p.name);
  const one = names.length === 1;
  const canPort = can("port.manage");
  const canVlan = can("vlan.manage");
  const canPoe = can("poe.manage");
  const canSec = can("netsec.manage");
  const anyPoe = sel.some((p) => p.poe);

  const req = (operation: string, params: Record<string, unknown>, locked: string[], title?: string) =>
    onChange({ operation, switchIds: [sw.id], params, lockedParams: locked, title });

  const rows = (data || []).filter((p) => {
    const st = portState(p);
    if (filter === "up") return p.oper_up;
    if (filter === "down") return !p.oper_up;
    if (filter === "errors") return st === "errors" || p.in_errors + p.out_errors > 0;
    if (filter === "poe") return p.poe && (p.poe.power_drawn_w || 0) > 0;
    return true;
  });

  return (
    <Loadable data={data} error={error} retry={() => mutate()}>
      {(ports) => (
        <div className="space-y-4">
          <Card
            title="Front panel"
            actions={
              selected.size > 0 ? (
                <>
                  <span className="text-xs text-muted">Selected: {names.join(", ")}</span>
                  <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                    Clear
                  </Button>
                </>
              ) : (
                <span className="text-xs text-muted">Click ports to select them for a change</span>
              )
            }
          >
            <PortPanel ports={ports} selected={selected} onToggle={toggle} />
            {selected.size > 0 && (canPort || canVlan || canPoe || canSec) && (
              <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
                {canPort && (
                  <>
                    <Button size="sm" onClick={() => req("port_admin", { ports: names, enabled: true }, ["ports", "enabled"], `Enable port(s) ${names.join(", ")}`)}>
                      Enable
                    </Button>
                    <Button size="sm" onClick={() => req("port_admin", { ports: names, enabled: false }, ["ports", "enabled"], `Disable port(s) ${names.join(", ")}`)}>
                      Disable
                    </Button>
                    <Button size="sm" onClick={() => req("port_description", { items: sel.map((p) => ({ port: p.name, description: p.description })) }, [], "Edit port descriptions")}>
                      Description…
                    </Button>
                    {one && (
                      <Button size="sm" onClick={() => req("port_speed", { port: names[0] }, ["port"])}>
                        Speed/duplex…
                      </Button>
                    )}
                  </>
                )}
                {canVlan && (
                  <Button size="sm" onClick={() => req("port_vlan", { ports: names }, ["ports"], `VLAN membership for port(s) ${names.join(", ")}`)}>
                    VLANs…
                  </Button>
                )}
                {canPoe && anyPoe && (
                  <>
                    <Button size="sm" onClick={() => req("poe_config", { ports: names }, ["ports"], `PoE settings for port(s) ${names.join(", ")}`)}>
                      PoE…
                    </Button>
                    {one && (
                      <Button size="sm" onClick={() => req("poe_restart", { port: names[0] }, ["port"], `Restart PoE on port ${names[0]}`)}>
                        Restart PoE
                      </Button>
                    )}
                  </>
                )}
                {canSec && mode === "pro" && (
                  <>
                    <Button size="sm" onClick={() => req("port_security", { ports: names }, ["ports"])}>
                      Port security…
                    </Button>
                    <Button size="sm" onClick={() => req("stp_protection", { ports: names }, ["ports"])}>
                      STP edge/BPDU…
                    </Button>
                  </>
                )}
              </div>
            )}
          </Card>

          <Card
            title="Ports"
            bodyClassName="p-0"
            actions={
              <div className="flex items-center rounded-md border border-line p-0.5 text-xs" role="group" aria-label="Port filter">
                {(["all", "up", "down", "errors", "poe"] as const).map((f) => (
                  <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)} className={filter === f ? "rounded bg-accent px-2 py-1 text-accent-fg" : "rounded px-2 py-1 text-muted"}>
                    {f === "poe" ? "PoE active" : f}
                  </button>
                ))}
              </div>
            }
          >
            {rows.length === 0 ? (
              <Empty>No ports match.</Empty>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th className="w-8" />
                    <Th>Port</Th>
                    <Th>Description</Th>
                    <Th>Status</Th>
                    <Th>Speed</Th>
                    <Th>VLAN</Th>
                    <Th className="text-right">In</Th>
                    <Th className="text-right">Out</Th>
                    <Th className="text-right">Errors</Th>
                    {mode === "pro" && <Th className="text-right">Discards</Th>}
                    {mode === "pro" && <Th className="text-right">Flaps</Th>}
                    <Th>PoE</Th>
                    <Th>Device</Th>
                    {mode === "pro" && <Th>Changed</Th>}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => (
                    <tr key={p.id} className={selected.has(p.name) ? "bg-accent/5" : "hover:bg-panel-2/50"}>
                      <Td>
                        <input type="checkbox" aria-label={`Select port ${p.name}`} checked={selected.has(p.name)} onChange={() => toggle(p.name)} />
                      </Td>
                      <Td>
                        <button type="button" className="font-medium hover:text-accent" onClick={() => setDetail(p)}>
                          {p.name}
                        </button>
                        {p.is_uplink && <Badge tone="info">uplink</Badge>}
                        {p.trunk_group && <Badge>{p.trunk_group}</Badge>}
                      </Td>
                      <Td className="max-w-48 truncate">{p.description || <span className="text-muted">–</span>}</Td>
                      <Td>
                        {!p.admin_up ? <Badge tone="bad">disabled</Badge> : p.oper_up ? <Badge tone="ok">up</Badge> : <Badge>down</Badge>}
                      </Td>
                      <Td className="tabular text-xs">{p.oper_up && p.speed_mbps ? `${p.speed_mbps >= 1000 ? `${p.speed_mbps / 1000}G` : `${p.speed_mbps}M`} ${p.duplex || ""}` : "–"}</Td>
                      <Td className="text-xs">
                        {p.untagged_vlan ?? "–"}
                        {p.tagged_vlans.length > 0 && <span className="text-muted"> +T {p.tagged_vlans.join(",")}</span>}
                      </Td>
                      <Td className="tabular text-right text-xs">{p.oper_up ? fmtBps(p.in_bps) : "–"}</Td>
                      <Td className="tabular text-right text-xs">{p.oper_up ? fmtBps(p.out_bps) : "–"}</Td>
                      <Td className={p.in_errors + p.out_errors ? "tabular text-right text-xs text-warn" : "tabular text-right text-xs"}>{fmtNum(p.in_errors + p.out_errors)}</Td>
                      {mode === "pro" && <Td className="tabular text-right text-xs">{fmtNum(p.in_discards + p.out_discards)}</Td>}
                      {mode === "pro" && <Td className="tabular text-right text-xs">{p.flap_count}</Td>}
                      <Td className="text-xs">
                        {p.poe ? (
                          p.poe.fault ? (
                            <Badge tone="bad">{p.poe.fault}</Badge>
                          ) : !p.poe.enabled ? (
                            <span className="text-muted">off</span>
                          ) : (p.poe.power_drawn_w || 0) > 0 ? (
                            `${p.poe.power_drawn_w} W`
                          ) : (
                            <span className="text-muted">{p.poe.detection_status}</span>
                          )
                        ) : (
                          "–"
                        )}
                      </Td>
                      <Td className="max-w-48 truncate text-xs">
                        {p.neighbors[0] ? p.neighbors[0].system_name : p.macs.length ? <span className="font-mono">{p.macs[0].mac}{p.macs.length > 1 ? ` +${p.macs.length - 1}` : ""}</span> : "–"}
                      </Td>
                      {mode === "pro" && <Td className="text-xs text-muted">{relTime(p.status_changed_at)}</Td>}
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
          <PortHistory sw={sw} port={detail} onClose={() => setDetail(null)} />
        </div>
      )}
    </Loadable>
  );
}
