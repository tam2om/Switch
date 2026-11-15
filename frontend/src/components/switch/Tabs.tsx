"use client";

import { HardwareBadge } from "@/components/HardwareBadge";
import { CheckCircle2, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { RangePicker, TimeChart, chartColors } from "@/components/Charts";
import type { ChangeRequest } from "@/components/ChangeDialog";
import {
  Badge, Button, Card, ConfirmDialog, Empty, ErrorBox, KV, Loadable, Meter, Notice, Pagination, StaleBadge,
  StatusBadge, Table, Td, Th, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtDate, fmtPct, fmtUptime, fmtWatts, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Backup, EventRow, Neighbor, Page, PoePort, SwitchDetail, SwitchVlan } from "@/lib/types";

type Range = "1h" | "6h" | "24h" | "7d" | "30d";

/* ------------------------------------------------------------------ overview */

export function OverviewTab({ sw }: { sw: SwitchDetail }) {
  const { mode } = useAuth();
  const m = sw.metrics;
  const caps = sw.capabilities || {};
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
      <Card title="Identity" className="xl:col-span-2">
        <KV
          items={[
            ["Hostname", sw.hostname],
            ["Management IP", <span key="ip" className="font-mono">{sw.mgmt_ip}</span>],
            ["Model", <>{sw.model_name || sw.product_number || "–"} <HardwareBadge sw={sw} /></>],
            ["Product number", sw.product_number || "–"],
            ["Serial number", sw.serial_number || "–"],
            ["Base MAC", <span key="mac" className="font-mono">{sw.base_mac || "–"}</span>],
            ["Firmware", sw.firmware || "–"],
            ["ROM", sw.rom_version || "–"],
            ["Site", sw.site || "–"],
            ["Location", [sw.location, sw.building && `Building ${sw.building}`, sw.floor && `Floor ${sw.floor}`].filter(Boolean).join(" · ") || "–"],
            ["Department", sw.department || "–"],
            ["Management VLAN", sw.mgmt_vlan ?? "–"],
            ["Uplink ports", sw.uplink_ports.join(", ") || "–"],
            ["Groups", sw.groups.map((g) => g.name).join(", ") || "–"],
          ]}
        />
        {sw.notes && <p className="mt-3 text-sm text-muted">{sw.notes}</p>}
      </Card>
      <Card title="Health" actions={<StaleBadge at={m?.at} stale={!!m?.stale} />}>
        <div className="space-y-3 text-sm">
          <div>
            <div className="flex justify-between"><span className="text-muted">CPU</span><span className="tabular">{fmtPct(m?.cpu_pct)}</span></div>
            <Meter value={m?.cpu_pct} />
          </div>
          <div>
            <div className="flex justify-between"><span className="text-muted">Memory</span><span className="tabular">{fmtPct(m?.mem_pct)}</span></div>
            <Meter value={m?.mem_pct} />
          </div>
          <div>
            <div className="flex justify-between"><span className="text-muted">PoE</span><span className="tabular">{fmtWatts(m?.poe_consumed_w)} / {fmtWatts(m?.poe_budget_w)}</span></div>
            <Meter value={m?.poe_consumed_w} max={m?.poe_budget_w || 0} />
          </div>
          <KV
            items={[
              ["Temperature", m?.temperature_c === null || m?.temperature_c === undefined ? "n/a" : `${m.temperature_c} °C`],
              ["Uptime", fmtUptime(m?.uptime_seconds)],
              ["Ports up", `${sw.ports_up} / ${sw.ports_total}`],
              ["VLANs", sw.vlan_count],
              ["Last poll", relTime(sw.last_poll_at)],
              ["Last success", relTime(sw.last_success_at)],
            ]}
          />
        </div>
      </Card>
      <Card title="Management access" className="xl:col-span-3">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {(["rest", "snmp", "ssh"] as const).map((p) => (
            <div key={p} className="rounded-md border border-line p-3 text-sm">
              <div className="flex items-center justify-between">
                <span className="font-medium uppercase">{p === "snmp" ? "SNMPv3" : p}</span>
                {sw.protocols[p] === false ? <Badge>disabled</Badge> : caps[p] ? <Badge tone="ok">reachable</Badge> : caps.probed_at ? <Badge tone="bad">unreachable</Badge> : <Badge>not probed</Badge>}
              </div>
              {p === "rest" && sw.rest_api_version && <div className="mt-1 text-xs text-muted">API version {sw.rest_api_version}</div>}
              {p === "ssh" && (
                <div className="mt-1 text-xs text-muted">
                  Host key {sw.ssh_host_key_trusted ? "trusted" : sw.ssh_host_key_fingerprint ? "fetched, not trusted" : "not fetched"}
                </div>
              )}
            </div>
          ))}
        </div>
        {caps.errors && caps.errors.length > 0 && (
          <div className="mt-3">
            <Notice tone="warn">{caps.errors.join("; ")}</Notice>
          </div>
        )}
        {mode === "pro" && caps.resources && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {Object.entries(caps.resources).map(([k, v]) => (
              <Badge key={k} tone={v ? "ok" : "bad"}>{k}</Badge>
            ))}
            <span className="text-xs text-muted">probed {relTime(caps.probed_at)}</span>
          </div>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------------------------------------------ VLANs */

export function VlansTab({ sw, onChange }: { sw: SwitchDetail; onChange: (r: ChangeRequest) => void }) {
  const { can } = useAuth();
  const { data, error, mutate } = useApi<SwitchVlan[]>(`/switches/${sw.id}/vlans`);
  return (
    <Card
      title="VLANs on this switch"
      bodyClassName="p-0"
      actions={can("vlan.manage") && <Button size="sm" variant="primary" onClick={() => onChange({ operation: "vlan_create", switchIds: [sw.id] })}>Create VLAN</Button>}
    >
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(vlans) =>
          vlans.length === 0 ? (
            <Empty>No VLAN data collected yet.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>ID</Th>
                  <Th>Name</Th>
                  <Th>Untagged ports</Th>
                  <Th>Tagged ports</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {vlans.map((v) => (
                  <tr key={v.vlan_id}>
                    <Td className="font-medium">
                      {v.vlan_id} {(v.is_management || v.vlan_id === sw.mgmt_vlan) && <Badge tone="accent">management</Badge>}
                    </Td>
                    <Td>{v.name}</Td>
                    <Td className="text-xs">{v.untagged_ports.join(", ") || "–"}</Td>
                    <Td className="text-xs">{v.tagged_ports.join(", ") || "–"}</Td>
                    <Td className="text-right">
                      {can("vlan.manage") && v.vlan_id !== 1 && (
                        <Button size="sm" variant="ghost" onClick={() => onChange({ operation: "vlan_delete", switchIds: [sw.id], params: { vlan_id: v.vlan_id }, lockedParams: ["vlan_id"], title: `Delete VLAN ${v.vlan_id} (${v.name})` })}>
                          Delete
                        </Button>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
    </Card>
  );
}

/* ------------------------------------------------------------------ PoE */

export function PoeTab({ sw, onChange }: { sw: SwitchDetail; onChange: (r: ChangeRequest) => void }) {
  const { can } = useAuth();
  const [range, setRange] = useState<Range>("24h");
  const { data, error, mutate } = useApi<{ budget_w: number | null; consumed_w: number | null; metrics_at: string | null; ports: PoePort[] }>(`/switches/${sw.id}/poe`, undefined, { live: true });
  const hist = useApi<{ points: Record<string, unknown>[] }>(`/metrics/switches/${sw.id}/poe`, { range });
  return (
    <Loadable data={data} error={error} retry={() => mutate()}>
      {(d) => (
        <div className="space-y-4">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            <Card title="Budget">
              <div className="tabular text-2xl font-semibold">{fmtWatts(d.consumed_w)}</div>
              <div className="mb-2 text-xs text-muted">of {fmtWatts(d.budget_w)} · updated {relTime(d.metrics_at)}</div>
              <Meter value={d.consumed_w} max={d.budget_w || 0} />
            </Card>
            <Card title="Power over time" className="md:col-span-2" actions={<RangePicker value={range} onChange={setRange} options={["1h", "6h", "24h", "7d", "30d"]} />}>
              <TimeChart data={hist.data?.points || []} height={140} format={(v) => fmtWatts(v)} series={[{ key: "power_w", label: "Power", color: chartColors.warn }]} />
            </Card>
          </div>
          <Card title="PoE ports" bodyClassName="p-0">
            {d.ports.length === 0 ? (
              <Empty>This switch does not report PoE ports.</Empty>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Port</Th>
                    <Th>Enabled</Th>
                    <Th>Status</Th>
                    <Th>Class</Th>
                    <Th>Priority</Th>
                    <Th>Allocation</Th>
                    <Th className="text-right">Drawn</Th>
                    <Th className="text-right">Allocated</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {d.ports.map((p) => (
                    <tr key={p.port}>
                      <Td className="font-medium">{p.port}</Td>
                      <Td>{p.enabled ? "yes" : <Badge>off</Badge>}</Td>
                      <Td>{p.fault ? <Badge tone="bad">{p.fault}</Badge> : <span className="text-sm">{p.detection_status}</span>}</Td>
                      <Td>{p.power_class ?? "–"}</Td>
                      <Td>{p.priority}</Td>
                      <Td>{p.allocation_method}</Td>
                      <Td className="tabular text-right">{fmtWatts(p.power_drawn_w)}</Td>
                      <Td className="tabular text-right">{fmtWatts(p.allocated_power_w)}</Td>
                      <Td className="whitespace-nowrap text-right">
                        {can("poe.manage") && (
                          <>
                            <Button size="sm" variant="ghost" onClick={() => onChange({ operation: "poe_config", switchIds: [sw.id], params: { ports: [p.port] }, lockedParams: ["ports"], title: `PoE settings for port ${p.port}` })}>
                              Configure
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => onChange({ operation: "poe_restart", switchIds: [sw.id], params: { port: p.port }, lockedParams: ["port"], title: `Restart PoE on port ${p.port}` })}>
                              Restart
                            </Button>
                          </>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      )}
    </Loadable>
  );
}

/* ------------------------------------------------------------------ devices */

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

export function DevicesTab({ sw }: { sw: SwitchDetail }) {
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useApi<Page<DeviceRow>>("/devices", { switch_id: sw.id, page, page_size: 100 });
  return (
    <Card title="Connected devices (MAC address table)" bodyClassName="p-0">
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) =>
          d.items.length === 0 ? (
            <Empty>No MAC addresses learned on access ports.</Empty>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>MAC</Th>
                    <Th>Vendor</Th>
                    <Th>Port</Th>
                    <Th>VLAN</Th>
                    <Th>LLDP</Th>
                    <Th>Last seen</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((m) => (
                    <tr key={`${m.mac}-${m.vlan_id}`}>
                      <Td className="font-mono">{m.mac}</Td>
                      <Td>{m.vendor || <span className="text-muted">unknown</span>}</Td>
                      <Td>{m.port}</Td>
                      <Td>{m.vlan_id ?? "–"}</Td>
                      <Td className="text-xs">{m.lldp ? `${m.lldp.system_name} (${m.lldp.remote_port})` : "–"}</Td>
                      <Td className="text-xs">{relTime(m.last_seen)} {!m.active && <Badge>inactive</Badge>}</Td>
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
  );
}

/* ------------------------------------------------------------------ neighbours */

export function NeighborsTab({ sw }: { sw: SwitchDetail }) {
  const { mode } = useAuth();
  const { data, error, mutate } = useApi<Neighbor[]>(`/switches/${sw.id}/neighbors`);
  return (
    <Card title="LLDP neighbours" bodyClassName="p-0">
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No LLDP neighbours discovered.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Local port</Th>
                  <Th>Neighbour</Th>
                  <Th>Remote port</Th>
                  <Th>Capabilities</Th>
                  {mode === "pro" && <Th>Chassis ID</Th>}
                  {mode === "pro" && <Th>Description</Th>}
                  <Th>Last seen</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((n) => (
                  <tr key={n.id}>
                    <Td className="font-medium">{n.local_port}</Td>
                    <Td>
                      {n.remote_switch_id ? <Link href={`/switches/${n.remote_switch_id}`} className="text-accent hover:underline">{n.system_name}</Link> : n.system_name || "–"}
                      {n.mgmt_address && <div className="font-mono text-xs text-muted">{n.mgmt_address}</div>}
                    </Td>
                    <Td>{n.remote_port_desc || n.remote_port}</Td>
                    <Td className="text-xs">{n.capabilities.map((c) => c.replace("CAP_", "").toLowerCase()).join(", ") || "–"}</Td>
                    {mode === "pro" && <Td className="font-mono text-xs">{n.chassis_id}</Td>}
                    {mode === "pro" && <Td className="max-w-64 truncate text-xs" >{n.system_description}</Td>}
                    <Td className="text-xs">{relTime(n.last_seen)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
    </Card>
  );
}

/* ------------------------------------------------------------------ monitoring */

export function MonitoringTab({ sw }: { sw: SwitchDetail }) {
  const [range, setRange] = useState<Range>("6h");
  const { data, error, mutate } = useApi<{ bucket: string; points: Record<string, unknown>[] }>(`/metrics/switches/${sw.id}`, { range }, { live: true });
  const pts = data?.points || [];
  const reach = pts.map((p) => ({ ...p, latency_ms: p.reachable === false ? null : p.latency_ms }));
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted">{data ? `Averaged per ${data.bucket}` : ""}</span>
        <RangePicker value={range} onChange={setRange} options={["1h", "6h", "24h", "7d", "30d"]} />
      </div>
      <ErrorBox error={error} onRetry={() => mutate()} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="CPU and memory">
          <TimeChart data={pts} area={false} domainMax={100} format={(v) => `${Math.round(v)}%`} series={[{ key: "cpu_pct", label: "CPU", color: chartColors.in }, { key: "mem_pct", label: "Memory", color: chartColors.sim }]} />
        </Card>
        <Card title="Traffic (sum of all ports)">
          <TimeChart data={pts} format={(v) => (v >= 1e6 ? `${(v / 1e6).toFixed(0)} Mbps` : `${(v / 1e3).toFixed(0)} Kbps`)} series={[{ key: "in_bps", label: "In", color: chartColors.in }, { key: "out_bps", label: "Out", color: chartColors.out }]} />
        </Card>
        <Card title="Temperature">
          <TimeChart data={pts} area={false} format={(v) => `${Math.round(v)} °C`} series={[{ key: "temperature_c", label: "Temperature", color: chartColors.warn }]} />
        </Card>
        <Card title="Management response time">
          <TimeChart data={reach} area={false} format={(v) => `${Math.round(v)} ms`} series={[{ key: "latency_ms", label: "Latency", color: chartColors.ok }]} />
          <p className="mt-2 text-xs text-muted">Gaps mean the switch did not answer the availability poll.</p>
        </Card>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ configuration */

export function ConfigTab({ sw, onChange }: { sw: SwitchDetail; onChange: (r: ChangeRequest) => void }) {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useApi<Page<Backup>>("/backups", { switch_id: sw.id, page, page_size: 20 });
  return (
    <Card
      title="Configuration backups"
      bodyClassName="p-0"
      actions={
        <>
          <Link href={`/backups?switch_id=${sw.id}`} className="text-xs text-accent">Compare / view all</Link>
          {can("backup.manage") && (
            <Button size="sm" variant="primary" onClick={() => onChange({ operation: "config_backup", switchIds: [sw.id], title: `Back up ${sw.hostname}` })}>
              Back up now
            </Button>
          )}
        </>
      }
    >
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) =>
          d.items.length === 0 ? (
            <Empty>No backups yet.</Empty>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Taken</Th>
                    <Th>Trigger</Th>
                    <Th>Size</Th>
                    <Th>Integrity</Th>
                    <Th>Restore tested</Th>
                    <Th>Note</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((b) => (
                    <tr key={b.id}>
                      <Td className="text-xs">{fmtDate(b.created_at)}</Td>
                      <Td>{b.trigger}</Td>
                      <Td className="tabular text-xs">{fmtBytes(b.size_bytes)}</Td>
                      <Td><StatusBadge status={b.verify_status} /></Td>
                      <Td>{b.restore_tested ? <Badge tone="ok">yes</Badge> : <span className="text-xs text-muted">no</span>}</Td>
                      <Td className="max-w-48 truncate text-xs">{b.note}</Td>
                      <Td className="whitespace-nowrap text-right">
                        <Link href={`/backups?view=${b.id}`} className="mr-2 text-xs text-accent">View</Link>
                        {can("config.restore") && b.verify_status === "verified" && (
                          <Button size="sm" variant="ghost" onClick={() => onChange({ operation: "config_restore", switchIds: [sw.id], params: { backup_id: b.id }, lockedParams: ["backup_id"], title: `Restore backup #${b.id} to ${sw.hostname}` })}>
                            Restore…
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <Pagination page={page} pageSize={20} total={d.total} onPage={setPage} />
            </>
          )
        }
      </Loadable>
    </Card>
  );
}

/* ------------------------------------------------------------------ security */

interface Posture {
  backup_id: number | null;
  backup_at: string | null;
  checks: { key: string; label: string; ok: boolean }[];
  ssh_host_key_trusted: boolean;
  ssh_host_key_fingerprint: string | null;
  mgmt_vlan: number | null;
}

const FIX_OPS: Record<string, string> = {
  authorized_managers: "authorized_managers",
  sntp: "sntp",
  dhcp_snooping: "dhcp_snooping",
  bpdu_protection: "stp_protection",
  port_security: "port_security",
  aaa: "aaa_server",
  telnet_disabled: "ssh_hardening",
  plaintext_web_disabled: "ssh_hardening",
  ssh_filetransfer: "ssh_hardening",
};

export function SecurityTab({ sw, onChange, reload }: { sw: SwitchDetail; onChange: (r: ChangeRequest) => void; reload: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const { data, error, mutate } = useApi<Posture>(`/switches/${sw.id}/security`);
  const [fetched, setFetched] = useState<{ fingerprint: string; changed: boolean; message: string } | null>(null);
  const [trustOpen, setTrustOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);

  const fetchKey = async () => {
    setBusy(true);
    setErr(null);
    try {
      setFetched(await api(`/switches/${sw.id}/ssh-host-key/fetch`, { method: "POST" }));
      reload();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Loadable data={data} error={error} retry={() => mutate()}>
      {(p) => (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Card title="Security posture" actions={p.backup_at && <span className="text-xs text-muted">from backup taken {relTime(p.backup_at)}</span>}>
            {p.checks.length === 0 ? (
              <Empty>Take a verified configuration backup to evaluate the security posture.</Empty>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {p.checks.map((c) => (
                  <li key={c.key} className="flex items-center gap-2">
                    {c.ok ? <CheckCircle2 className="h-4 w-4 text-ok" aria-label="pass" /> : <XCircle className="h-4 w-4 text-bad" aria-label="fail" />}
                    <span className="flex-1">{c.label}</span>
                    {!c.ok && can("netsec.manage") && FIX_OPS[c.key] && (
                      <Button size="sm" variant="ghost" onClick={() => onChange({ operation: FIX_OPS[c.key], switchIds: [sw.id] })}>
                        Fix…
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-muted">Checks are evaluated against the stored configuration text; nothing is read from the switch.</p>
          </Card>
          <Card title="SSH host key">
            <div className="space-y-3 text-sm">
              <KV
                items={[
                  ["Status", p.ssh_host_key_trusted ? <Badge key="t" tone="ok">trusted</Badge> : p.ssh_host_key_fingerprint ? <Badge key="t" tone="warn">not trusted</Badge> : <Badge key="t">not fetched</Badge>],
                  ["Fingerprint", <span key="f" className="font-mono text-xs">{p.ssh_host_key_fingerprint || "–"}</span>],
                ]}
              />
              <p className="text-xs text-muted">SSH is only used after the host key is explicitly trusted. Unknown or changed keys are rejected.</p>
              {fetched && (
                <Notice tone={fetched.changed ? "bad" : "info"}>
                  {fetched.changed && <strong className="block">The host key has CHANGED since it was last trusted. Investigate before trusting it.</strong>}
                  Fetched fingerprint <span className="font-mono">{fetched.fingerprint}</span>. {fetched.message}
                </Notice>
              )}
              <ErrorBox error={err} />
              {can("credential.manage") && (
                <div className="flex gap-2">
                  <Button onClick={fetchKey} loading={busy}>Fetch host key</Button>
                  {p.ssh_host_key_fingerprint && !p.ssh_host_key_trusted && (
                    <Button variant="primary" onClick={() => setTrustOpen(true)}>Trust fingerprint…</Button>
                  )}
                </div>
              )}
            </div>
          </Card>
          {can("netsec.manage") && (
            <Card title="Network security changes" className="xl:col-span-2">
              <div className="flex flex-wrap gap-2">
                {[
                  ["snmpv3_user", "SNMPv3 user"],
                  ["authorized_managers", "Authorized managers"],
                  ["aaa_server", "RADIUS / TACACS+"],
                  ["dhcp_snooping", "DHCP snooping"],
                  ["ssh_hardening", "SSH hardening"],
                  ["sntp", "SNTP"],
                ].map(([op, label]) => (
                  <Button key={op} size="sm" onClick={() => onChange({ operation: op, switchIds: [sw.id] })}>
                    {label}…
                  </Button>
                ))}
              </div>
            </Card>
          )}
          <ConfirmDialog
            open={trustOpen}
            onClose={() => setTrustOpen(false)}
            title="Trust SSH host key"
            message={
              <>
                Only trust this key after comparing it with the output of <code>show crypto host-public-key fingerprint</code> on the switch console.
                <div className="mt-2 font-mono text-xs">{p.ssh_host_key_fingerprint}</div>
              </>
            }
            confirmLabel="Trust"
            onConfirm={async () => {
              await api(`/switches/${sw.id}/ssh-host-key/trust`, { method: "POST", body: { fingerprint: p.ssh_host_key_fingerprint } });
              toast("ok", "Host key trusted");
              mutate();
              reload();
            }}
          />
        </div>
      )}
    </Loadable>
  );
}

/* ------------------------------------------------------------------ events */

export function EventsTab({ sw }: { sw: SwitchDetail }) {
  const { data, error, mutate } = useApi<EventRow[]>(`/switches/${sw.id}/events`, { limit: 200 }, { live: true });
  return (
    <Card title="Events" bodyClassName="p-0">
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No events recorded for this switch.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Time</Th>
                  <Th>Severity</Th>
                  <Th>Type</Th>
                  <Th>Message</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <Td className="whitespace-nowrap text-xs">{fmtDate(e.ts)}</Td>
                    <Td><StatusBadge status={e.severity} /></Td>
                    <Td className="text-xs text-muted">{e.type}</Td>
                    <Td>{e.message}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
    </Card>
  );
}

