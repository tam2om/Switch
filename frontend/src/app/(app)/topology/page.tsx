"use client";

import { Minus, Plus } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge, Button, Card, Checkbox, ConfirmDialog, ErrorBox, Field, Input, Loadable, Modal, PageHeader, Select, SimBadge, StatusBadge, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";

interface TNode {
  id: string;
  label: string;
  kind: "switch" | "device";
  switch_id?: number;
  status?: string;
  is_simulated?: boolean;
  mgmt_ip?: string;
  building?: string;
  description?: string;
}
interface TEdge {
  id: string;
  source: string;
  target: string;
  source_port: string;
  target_port: string;
  kind: string;
  source_type: string;
  link_up: boolean | null;
  vlans: { untagged: number | null; tagged: number[] } | null;
}

const STATUS_COLOR: Record<string, string> = {
  online: "var(--c-ok)",
  offline: "var(--c-bad)",
  warning: "var(--c-warn)",
};

const COL_W = 230;
const ROW_H = 74;

function layout(nodes: TNode[], edges: TEdge[]) {
  const switches = nodes.filter((n) => n.kind === "switch");
  const buildings = Array.from(new Set(switches.map((s) => s.building || "Unassigned"))).sort();
  const pos: Record<string, { x: number; y: number }> = {};
  buildings.forEach((b, ci) => {
    switches
      .filter((s) => (s.building || "Unassigned") === b)
      .sort((a, c) => a.label.localeCompare(c.label, undefined, { numeric: true }))
      .forEach((s, ri) => {
        pos[s.id] = { x: 90 + ci * COL_W, y: 70 + ri * ROW_H };
      });
  });
  // Devices fan out to the right of the switch they hang off.
  const perSwitch: Record<string, number> = {};
  for (const e of edges) {
    const dev = nodes.find((n) => n.id === e.target && n.kind === "device");
    if (!dev || pos[dev.id] || !pos[e.source]) continue;
    const k = (perSwitch[e.source] = (perSwitch[e.source] || 0) + 1);
    const p = pos[e.source];
    pos[dev.id] = { x: p.x + 70 + ((k - 1) % 3) * 22, y: p.y - 22 + Math.floor((k - 1) / 3) * 14 };
  }
  const maxRows = Math.max(1, ...buildings.map((b) => switches.filter((s) => (s.building || "Unassigned") === b).length));
  return { pos, buildings, width: Math.max(600, buildings.length * COL_W + 80), height: maxRows * ROW_H + 80 };
}

function AddLinkDialog({ open, onClose, switches, onSaved }: { open: boolean; onClose: () => void; switches: TNode[]; onSaved: () => void }) {
  const [f, setF] = useState({ switch_id: "", local_port: "", remote_switch_id: "", remote_name: "", remote_port: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api("/topology/links", {
        method: "POST",
        body: {
          switch_id: Number(f.switch_id),
          local_port: f.local_port,
          remote_switch_id: f.remote_switch_id ? Number(f.remote_switch_id) : null,
          remote_name: f.remote_name,
          remote_port: f.remote_port,
        },
      });
      onSaved();
      onClose();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Add manual link"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={save} disabled={!f.switch_id || !f.local_port}>Add link</Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-muted">Document a connection that LLDP cannot see (for example a device without LLDP). It is shown as a manual link.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Switch" htmlFor="l-sw">
            <Select id="l-sw" value={f.switch_id} onChange={(e) => setF({ ...f, switch_id: e.target.value })}>
              <option value="">Select…</option>
              {switches.map((s) => <option key={s.id} value={s.switch_id}>{s.label}</option>)}
            </Select>
          </Field>
          <Field label="Local port" htmlFor="l-lp">
            <Input id="l-lp" value={f.local_port} onChange={(e) => setF({ ...f, local_port: e.target.value })} />
          </Field>
          <Field label="Remote switch" htmlFor="l-rs">
            <Select id="l-rs" value={f.remote_switch_id} onChange={(e) => setF({ ...f, remote_switch_id: e.target.value })}>
              <option value="">— other device —</option>
              {switches.map((s) => <option key={s.id} value={s.switch_id}>{s.label}</option>)}
            </Select>
          </Field>
          <Field label="Remote name" htmlFor="l-rn" hint="Required when the remote end is not a managed switch.">
            <Input id="l-rn" value={f.remote_name} disabled={!!f.remote_switch_id} onChange={(e) => setF({ ...f, remote_name: e.target.value })} />
          </Field>
          <Field label="Remote port" htmlFor="l-rp">
            <Input id="l-rp" value={f.remote_port} onChange={(e) => setF({ ...f, remote_port: e.target.value })} />
          </Field>
        </div>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

export default function TopologyPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [devices, setDevices] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [sel, setSel] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [delEdge, setDelEdge] = useState<TEdge | null>(null);
  const { data, error, mutate } = useApi<{ nodes: TNode[]; edges: TEdge[] }>("/topology", { include_devices: devices }, { live: true });

  const model = useMemo(() => {
    if (!data) return null;
    // Collapse the two LLDP directions of the same switch-to-switch cable into one line.
    const seen = new Set<string>();
    const edges = data.edges.filter((e) => {
      const k = [e.source + ":" + e.source_port, e.target + ":" + e.target_port].sort().join("|");
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
    return { ...layout(data.nodes, edges), edges, nodes: data.nodes };
  }, [data]);

  const selNode = data?.nodes.find((n) => n.id === sel) || null;
  const selEdges = model?.edges.filter((e) => e.source === sel || e.target === sel) || [];
  const label = (id: string) => data?.nodes.find((n) => n.id === id)?.label || id;

  return (
    <div>
      <PageHeader
        title="Topology"
        subtitle="Built from LLDP neighbour data, grouped by building"
        actions={
          <>
            <Checkbox label="Show LLDP devices" checked={devices} onChange={setDevices} />
            <Button size="sm" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(0.4, z - 0.15))}><Minus className="h-4 w-4" /></Button>
            <Button size="sm" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(2, z + 0.15))}><Plus className="h-4 w-4" /></Button>
            {can("switch.manage") && <Button size="sm" onClick={() => setAdding(true)}>Add manual link</Button>}
          </>
        }
      />
      <Loadable data={model ?? undefined} error={error} retry={() => mutate()}>
        {(m) => (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
            <Card bodyClassName="p-0">
              <div className="max-h-[75vh] overflow-auto">
                <svg width={m.width * zoom} height={m.height * zoom} viewBox={`0 0 ${m.width} ${m.height}`} role="img" aria-label="Network topology diagram">
                  {m.buildings.map((b, i) => (
                    <text key={b} x={90 + i * COL_W} y={28} textAnchor="middle" fill="var(--c-muted)" fontSize={12} fontWeight={600}>
                      Building {b}
                    </text>
                  ))}
                  {m.edges.map((e) => {
                    const a = m.pos[e.source];
                    const b = m.pos[e.target];
                    if (!a || !b) return null;
                    const hl = sel && (e.source === sel || e.target === sel);
                    const down = e.link_up === false;
                    return (
                      <line
                        key={e.id}
                        x1={a.x}
                        y1={a.y}
                        x2={b.x}
                        y2={b.y}
                        stroke={down ? "var(--c-bad)" : hl ? "var(--c-accent)" : e.kind === "device" ? "var(--c-line)" : "var(--c-muted)"}
                        strokeWidth={hl ? 2.5 : e.kind === "device" ? 1 : 1.5}
                        strokeDasharray={down || e.source_type === "manual" ? "5 4" : undefined}
                        opacity={sel && !hl ? 0.25 : 0.9}
                      />
                    );
                  })}
                  {m.nodes.map((n) => {
                    const p = m.pos[n.id];
                    if (!p) return null;
                    if (n.kind === "device") {
                      return (
                        <g key={n.id} onClick={() => setSel(n.id)} className="cursor-pointer">
                          <circle cx={p.x} cy={p.y} r={5} fill="var(--c-info)" stroke={sel === n.id ? "var(--c-accent)" : "none"} strokeWidth={2} />
                          <title>{n.label}</title>
                        </g>
                      );
                    }
                    return (
                      <g key={n.id} onClick={() => setSel(n.id)} className="cursor-pointer">
                        <rect x={p.x - 62} y={p.y - 16} width={124} height={32} rx={6} fill="var(--c-panel-2)" stroke={sel === n.id ? "var(--c-accent)" : STATUS_COLOR[n.status || ""] || "var(--c-line)"} strokeWidth={sel === n.id ? 2.5 : 1.5} />
                        <circle cx={p.x - 50} cy={p.y} r={4} fill={STATUS_COLOR[n.status || ""] || "var(--c-muted)"} />
                        <text x={p.x + 4} y={p.y + 4} textAnchor="middle" fill="var(--c-fg)" fontSize={11}>
                          {n.label.length > 16 ? n.label.slice(0, 15) + "…" : n.label}
                        </text>
                        {n.is_simulated && (
                          <text x={p.x} y={p.y + 27} textAnchor="middle" fill="var(--c-sim)" fontSize={9}>SIMULATED</text>
                        )}
                        <title>{`${n.label} (${n.mgmt_ip}) – ${n.status}`}</title>
                      </g>
                    );
                  })}
                </svg>
              </div>
            </Card>
            <Card title={selNode ? selNode.label : "Details"}>
              {!selNode ? (
                <p className="text-sm text-muted">Select a switch or device to see its links. Dashed red lines are links that are down; dashed grey lines are manual links.</p>
              ) : (
                <div className="space-y-3 text-sm">
                  {selNode.kind === "switch" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={selNode.status || "unknown"} /> <SimBadge show={!!selNode.is_simulated} />
                      <span className="font-mono text-xs text-muted">{selNode.mgmt_ip}</span>
                      <Link href={`/switches/${selNode.switch_id}?tab=neighbors`} className="text-accent hover:underline">Open switch</Link>
                    </div>
                  ) : (
                    <p className="text-muted">{selNode.description || "LLDP device"}</p>
                  )}
                  <ul className="space-y-1.5">
                    {selEdges.map((e) => {
                      const other = e.source === sel ? e.target : e.source;
                      const myPort = e.source === sel ? e.source_port : e.target_port;
                      const otherPort = e.source === sel ? e.target_port : e.source_port;
                      return (
                        <li key={e.id} className="rounded border border-line p-2">
                          <div>
                            Port <strong>{myPort}</strong> → {label(other)} <span className="text-muted">port {otherPort || "?"}</span>
                          </div>
                          <div className="mt-1 flex flex-wrap gap-1">
                            {e.link_up === false && <Badge tone="bad">down</Badge>}
                            <Badge>{e.source_type}</Badge>
                            {e.vlans && (
                              <Badge tone="info">
                                VLAN {e.vlans.untagged ?? "–"}
                                {e.vlans.tagged.length ? ` + ${e.vlans.tagged.join(",")}` : ""}
                              </Badge>
                            )}
                            {e.source_type === "manual" && can("switch.manage") && (
                              <button type="button" className="text-xs text-bad underline" onClick={() => setDelEdge(e)}>remove</button>
                            )}
                          </div>
                        </li>
                      );
                    })}
                    {selEdges.length === 0 && <li className="text-muted">No links.</li>}
                  </ul>
                </div>
              )}
            </Card>
          </div>
        )}
      </Loadable>
      <AddLinkDialog open={adding} onClose={() => setAdding(false)} switches={(data?.nodes || []).filter((n) => n.kind === "switch")} onSaved={() => { toast("ok", "Link added"); mutate(); }} />
      <ConfirmDialog
        open={!!delEdge}
        onClose={() => setDelEdge(null)}
        title="Remove manual link"
        message="The manually documented link will be removed from the topology."
        confirmLabel="Remove"
        onConfirm={async () => {
          await api(`/topology/links/${delEdge!.id.replace(/^e/, "")}`, { method: "DELETE" });
          mutate();
        }}
      />
    </div>
  );
}
