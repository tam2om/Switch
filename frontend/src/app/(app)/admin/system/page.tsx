"use client";

import { useState } from "react";
import { CREDIT_TEXT } from "@/components/Credit";
import { Badge, Button, Card, ConfirmDialog, Field, Input, KV, Loadable, Notice, PageHeader, Select, StatusBadge, Table, Tabs, Td, Th, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page, PollingJob, SwitchRow } from "@/lib/types";

interface Health {
  time: string;
  environment: string;
  simulator_enabled: boolean;
  database: { ok: boolean; version?: string; size_bytes?: number; timescaledb?: string | null; migration?: string; error?: string };
  redis: { ok: boolean; version?: string; queues?: Record<string, number>; error?: string };
  storage: { backend: string; ok: boolean; error?: string };
  workers: { ok: boolean; count: number; nodes: string[]; error?: string };
  polling: PollingJob[];
  switches: Record<string, number>;
}

interface Capability {
  family: string;
  firmware: string;
  key: string;
  protocol: string;
  resource: string;
  evidence: string;
  write: boolean;
  fallback: string | null;
  notes: string;
}

function Ok({ ok }: { ok: boolean }) {
  return ok ? <Badge tone="ok">healthy</Badge> : <Badge tone="bad">problem</Badge>;
}

function HealthTab() {
  const { data, error, mutate } = useApi<Health>("/system/health", undefined, { live: true });
  return (
    <Loadable data={data} error={error} retry={() => mutate()}>
      {(h) => (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <Card title="Database" actions={<Ok ok={h.database.ok} />}>
            <KV items={[["Version", h.database.version || h.database.error || "–"], ["TimescaleDB", h.database.timescaledb || "not installed"], ["Size", fmtBytes(h.database.size_bytes)], ["Schema migration", h.database.migration || "–"]]} />
          </Card>
          <Card title="Redis and queues" actions={<Ok ok={h.redis.ok} />}>
            <KV items={[["Version", h.redis.version || h.redis.error || "–"], ...Object.entries(h.redis.queues || {}).map(([k, v]) => [`Queue "${k}"`, `${v} waiting`] as [string, string])]} />
          </Card>
          <Card title="Background workers" actions={<Ok ok={h.workers.ok} />}>
            {h.workers.ok ? (
              <KV items={[["Workers", h.workers.count], ["Nodes", h.workers.nodes.join(", ")]]} />
            ) : (
              <Notice tone="bad">No worker answered. Polling, backups and changes will not run until a worker is available{h.workers.error ? ` (${h.workers.error})` : ""}.</Notice>
            )}
          </Card>
          <Card title="Backup storage" actions={<Ok ok={h.storage.ok} />}>
            <KV items={[["Backend", h.storage.backend], ["Status", h.storage.error || "reachable"]]} />
          </Card>
          <Card title="Application" className="xl:col-span-2">
            <KV
              items={[
                ["Environment", h.environment],
                ["Simulator", h.simulator_enabled ? "enabled" : "disabled"],
                ["Server time", fmtDate(h.time)],
                ["Switches", Object.entries(h.switches).map(([k, v]) => `${v} ${k}`).join(", ") || "none"],
                ["About", CREDIT_TEXT],
              ]}
            />
            <Table className="mt-3">
              <thead><tr><Th>Polling</Th><Th>Last run</Th><Th>Result</Th><Th>Failed</Th></tr></thead>
              <tbody>
                {h.polling.map((p) => (
                  <tr key={p.category}>
                    <Td>{p.category}</Td>
                    <Td className="text-xs">{relTime(p.last_run_at)}</Td>
                    <Td><StatusBadge status={p.last_status} /></Td>
                    <Td className="tabular">{p.switches_failed}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      )}
    </Loadable>
  );
}

function CapabilitiesTab() {
  const { data, error } = useApi<{ registry: Capability[]; observed_on_real_switches: Record<string, { ok: number; failed: number }> }>("/capabilities/matrix");
  return (
    <Card bodyClassName="p-0" title="AOS-Switch 16.11 capability registry">
      <p className="px-4 pt-3 text-xs text-muted">
        Evidence “documented” means taken from Aruba documentation and exercised against the simulator only. Nothing becomes “verified” until it has been tested
        on a physical switch. The observed columns count results from real (non-simulated) switches only.
      </p>
      <Loadable data={data} error={error}>
        {(d) => (
          <Table>
            <thead>
              <tr>
                <Th>Capability</Th>
                <Th>Protocol</Th>
                <Th>Resource</Th>
                <Th>Write</Th>
                <Th>Fallback</Th>
                <Th>Evidence</Th>
                <Th>Observed on hardware</Th>
              </tr>
            </thead>
            <tbody>
              {d.registry.map((c) => {
                const o = d.observed_on_real_switches[c.key];
                return (
                  <tr key={c.key}>
                    <Td className="font-mono text-xs">{c.key}</Td>
                    <Td>{c.protocol}</Td>
                    <Td className="max-w-80 text-xs">{c.resource}{c.notes && <div className="text-muted">{c.notes}</div>}</Td>
                    <Td>{c.write ? <Badge tone="warn">write</Badge> : "read"}</Td>
                    <Td className="font-mono text-xs">{c.fallback || "–"}</Td>
                    <Td><Badge tone={c.evidence === "verified" ? "ok" : "muted"}>{c.evidence}</Badge></Td>
                    <Td className="text-xs">{o ? `${o.ok} ok / ${o.failed} failed` : <span className="text-muted">pending</span>}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </Loadable>
    </Card>
  );
}

function SimulatorTab() {
  const { can } = useAuth();
  const toast = useToast();
  const status = useApi<{ enabled: boolean; simulated_switches: number }>("/simulator/status");
  const sw = useApi<Page<SwitchRow>>("/switches", { simulated: true, page_size: 500 });
  const [count, setCount] = useState("10");
  const [target, setTarget] = useState("");
  const [port, setPort] = useState("");
  const [busy, setBusy] = useState(false);
  const [remove, setRemove] = useState(false);
  const run = async (fn: () => Promise<unknown>, msg: string) => {
    setBusy(true);
    try {
      await fn();
      toast("ok", msg);
      status.mutate();
      sw.mutate();
    } catch (e) {
      toast("bad", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const fault = (body: Record<string, unknown>, msg: string) => run(() => api(`/simulator/switches/${target}/fault`, { method: "POST", body }), msg);
  if (status.data && !status.data.enabled) {
    return <Notice tone="info">The simulator is disabled on this server (ANM_SIMULATOR_ENABLED=false). This is the expected production setting.</Notice>;
  }
  return (
    <div className="space-y-4">
      <Notice tone="sim">
        The simulator generates fake AOS-Switch switches (Aruba 2540; fleets of 10 or more also include one 5406R zl2 chassis and one 2930F-8G) for testing and demonstrations. Simulated switches are always labelled SIMULATED and use the reserved
        198.18.0.0/15 test range. Disable it in production.
      </Notice>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Simulated fleet">
          <p className="mb-3 text-sm">{status.data?.simulated_switches ?? "…"} simulated switch(es) in the inventory.</p>
          {can("settings.manage") && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Number of switches" htmlFor="sim-n">
                <Input id="sim-n" type="number" min={1} max={200} className="w-32" value={count} onChange={(e) => setCount(e.target.value)} />
              </Field>
              <Button loading={busy} onClick={() => run(() => api("/simulator/seed", { method: "POST", body: { count: Number(count) } }), "Simulated switches created")}>Seed</Button>
              <Button variant="danger" onClick={() => setRemove(true)}>Remove all simulated</Button>
            </div>
          )}
        </Card>
        {can("settings.manage") && (
          <Card title="Inject faults (testing)">
            <div className="space-y-3">
              <Field label="Simulated switch" htmlFor="sim-sw">
                <Select id="sim-sw" value={target} onChange={(e) => setTarget(e.target.value)}>
                  <option value="">Select…</option>
                  {sw.data?.items.map((s) => <option key={s.id} value={s.id}>{s.hostname}</option>)}
                </Select>
              </Field>
              <Field label="Port (for port faults)" htmlFor="sim-port">
                <Input id="sim-port" className="w-32" value={port} onChange={(e) => setPort(e.target.value)} />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={!target || busy} onClick={() => fault({ offline: true }, "Switch taken offline")}>Take offline</Button>
                <Button size="sm" disabled={!target || busy} onClick={() => fault({ offline: false }, "Switch back online")}>Bring online</Button>
                <Button size="sm" disabled={!target || !port || busy} onClick={() => fault({ poe_fault_port: port }, "PoE fault injected")}>PoE fault on port</Button>
                <Button size="sm" disabled={!target || !port || busy} onClick={() => fault({ flapping_port: port }, "Port flapping injected")}>Flap port</Button>
                <Button size="sm" variant="ghost" disabled={!target || busy} onClick={() => fault({ clear: true }, "Faults cleared")}>Clear faults</Button>
              </div>
              <p className="text-xs text-muted">Effects appear after the next polling cycle.</p>
            </div>
          </Card>
        )}
      </div>
      <ConfirmDialog
        open={remove}
        onClose={() => setRemove(false)}
        danger
        title="Remove simulated switches"
        typeToConfirm="SIMULATED"
        message="All simulated switches and their data are removed from the inventory. Real switches are not affected."
        confirmLabel="Remove"
        onConfirm={() => run(() => api("/simulator", { method: "DELETE" }), "Simulated switches removed")}
      />
    </div>
  );
}

type Tab = "health" | "capabilities" | "simulator";

export default function SystemPage() {
  const { me } = useAuth();
  const [tab, setTab] = useState<Tab>("health");
  return (
    <div>
      <PageHeader title="System health" />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "health", label: "Services" },
          { id: "capabilities", label: "Device capabilities" },
          { id: "simulator", label: "Simulator", hidden: !me?.simulator_enabled },
        ]}
      />
      {tab === "health" && <HealthTab />}
      {tab === "capabilities" && <CapabilitiesTab />}
      {tab === "simulator" && <SimulatorTab />}
    </div>
  );
}
