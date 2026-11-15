"use client";

import { Plus, Radar, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ChangeDialog, type ChangeRequest } from "@/components/ChangeDialog";
import { SwitchForm } from "@/components/SwitchForm";
import {
  Badge, Button, Card, Empty, ErrorBox, Field, Input, Loadable, Meter, Modal, PageHeader, Pagination, Select,
  SimBadge, StaleBadge, StatusBadge, Table, Td, Th, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtPct, fmtWatts, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Page, Site, SwitchRow } from "@/lib/types";

interface DiscoverResult {
  cidr: string;
  scanned: number;
  found: { mgmt_ip: string; hostname: string; product_number: string | null; firmware: string | null; exists: boolean }[];
  added: string[];
}

function DiscoverDialog({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: () => void }) {
  const [cidr, setCidr] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [res, setRes] = useState<DiscoverResult | null>(null);
  const run = async (add: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<DiscoverResult>("/switches/discover", { method: "POST", body: { cidr, add } });
      setRes(r);
      if (add) onAdded();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const addable = res?.found.filter((f) => !f.exists && f.product_number).length || 0;
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Discover switches"
      wide
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          <Button onClick={() => run(false)} loading={busy} disabled={!cidr}>
            Scan
          </Button>
          {res && addable > 0 && !res.added.length && (
            <Button variant="primary" onClick={() => run(true)} loading={busy}>
              Add {addable} new switch{addable === 1 ? "" : "es"}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-muted">
          Scans a subnet (up to /24) with SNMPv3 using the fleet default monitoring credential. Only devices that answer are listed. Nothing is changed on
          the devices.
        </p>
        <Field label="Subnet (CIDR)" htmlFor="cidr">
          <Input id="cidr" placeholder="10.20.30.0/24" value={cidr} onChange={(e) => setCidr(e.target.value)} />
        </Field>
        <ErrorBox error={err} />
        {res && (
          <div>
            <p className="mb-2">
              Scanned {res.scanned} address(es), {res.found.length} responded.
              {res.added.length > 0 && <span className="text-ok"> Added {res.added.length}.</span>}
            </p>
            {res.found.length > 0 && (
              <Table>
                <thead>
                  <tr>
                    <Th>IP</Th>
                    <Th>Hostname</Th>
                    <Th>Model</Th>
                    <Th>Firmware</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {res.found.map((f) => (
                    <tr key={f.mgmt_ip}>
                      <Td className="font-mono">{f.mgmt_ip}</Td>
                      <Td>{f.hostname}</Td>
                      <Td>{f.product_number || <span className="text-warn">not an AOS-Switch</span>}</Td>
                      <Td>{f.firmware || "–"}</Td>
                      <Td>{f.exists ? <Badge>already managed</Badge> : res.added.includes(f.mgmt_ip) ? <Badge tone="ok">added</Badge> : null}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </div>
        )}
      </div>
    </Modal>
  );
}

export default function SwitchesPage() {
  const { can, mode } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [siteId, setSiteId] = useState("");
  const [building, setBuilding] = useState("");
  const [sim, setSim] = useState("");
  const [sort, setSort] = useState("hostname");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [adding, setAdding] = useState(false);
  const [discover, setDiscover] = useState(false);
  const [change, setChange] = useState<ChangeRequest | null>(null);
  const pageSize = 50;
  const { data, error, mutate } = useApi<Page<SwitchRow>>(
    "/switches",
    { q, status, site_id: siteId, building, simulated: sim, sort, page, page_size: pageSize },
    { live: true },
  );
  const sites = useApi<Site[]>("/sites");

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const allOnPage = data?.items.every((s) => selected.has(s.id)) && !!data?.items.length;

  const pollNow = async (id: number) => {
    try {
      await api(`/switches/${id}/poll`, { method: "POST", query: { category: "inventory" } });
      toast("ok", "Poll completed");
      mutate();
    } catch (e) {
      toast("bad", e instanceof Error ? e.message : "Poll failed");
    }
  };

  return (
    <div>
      <PageHeader
        title="Switches"
        subtitle={data ? `${data.total} switch(es)` : undefined}
        actions={
          <>
            {can("switch.manage") && (
              <Button onClick={() => setDiscover(true)}>
                <Radar className="h-4 w-4" /> Discover
              </Button>
            )}
            {can("switch.manage") && (
              <Button variant="primary" onClick={() => setAdding(true)}>
                <Plus className="h-4 w-4" /> Add switch
              </Button>
            )}
          </>
        }
      />

      <Card bodyClassName="p-0">
        <div className="flex flex-wrap items-end gap-2 border-b border-line p-3">
          <div className="w-64">
            <Input placeholder="Hostname, IP, serial, location…" aria-label="Filter switches" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Status" className="w-36" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {["online", "offline", "warning", "unknown", "maintenance"].map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </Select>
          <Select aria-label="Site" className="w-44" value={siteId} onChange={(e) => { setSiteId(e.target.value); setPage(1); }}>
            <option value="">All sites</option>
            {sites.data?.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </Select>
          <div className="w-32">
            <Input placeholder="Building" aria-label="Building" value={building} onChange={(e) => { setBuilding(e.target.value); setPage(1); }} />
          </div>
          <Select aria-label="Simulated" className="w-40" value={sim} onChange={(e) => { setSim(e.target.value); setPage(1); }}>
            <option value="">Real and simulated</option>
            <option value="false">Real hardware only</option>
            <option value="true">Simulated only</option>
          </Select>
          <Select aria-label="Sort" className="w-36" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="hostname">Sort: hostname</option>
            <option value="mgmt_ip">Sort: IP</option>
            <option value="status">Sort: status</option>
            <option value="location">Sort: location</option>
          </Select>
          {selected.size > 0 && (
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted">{selected.size} selected</span>
              {can("backup.manage") && (
                <Button size="sm" onClick={() => setChange({ operation: "config_backup", switchIds: [...selected], title: "Back up selected switches" })}>
                  Back up now
                </Button>
              )}
              {can("bulk.execute") && (
                <Button size="sm" variant="primary" onClick={() => router.push(`/changes/new?switches=${[...selected].join(",")}`)}>
                  Bulk change…
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
                Clear
              </Button>
            </div>
          )}
        </div>
        <Loadable data={data} error={error} retry={() => mutate()}>
          {(d) =>
            d.items.length === 0 ? (
              <Empty>No switches match these filters.</Empty>
            ) : (
              <>
                <Table>
                  <thead>
                    <tr>
                      <Th className="w-8">
                        <input
                          type="checkbox"
                          aria-label="Select all on page"
                          checked={allOnPage}
                          onChange={() =>
                            setSelected((s) => {
                              const n = new Set(s);
                              d.items.forEach((x) => (allOnPage ? n.delete(x.id) : n.add(x.id)));
                              return n;
                            })
                          }
                        />
                      </Th>
                      <Th>Switch</Th>
                      <Th>Status</Th>
                      <Th>Location</Th>
                      {mode === "pro" && <Th>Model</Th>}
                      {mode === "pro" && <Th>Firmware</Th>}
                      <Th>CPU</Th>
                      <Th>Memory</Th>
                      <Th>PoE</Th>
                      <Th>Last poll</Th>
                      {can("switch.manage") && <Th />}
                    </tr>
                  </thead>
                  <tbody>
                    {d.items.map((s) => (
                      <tr key={s.id} className="hover:bg-panel-2/50">
                        <Td>
                          <input type="checkbox" aria-label={`Select ${s.hostname}`} checked={selected.has(s.id)} onChange={() => toggle(s.id)} />
                        </Td>
                        <Td>
                          <Link href={`/switches/${s.id}`} className="font-medium hover:text-accent">{s.hostname}</Link>{" "}
                          <SimBadge show={s.is_simulated} />
                          <div className="font-mono text-xs text-muted">{s.mgmt_ip}</div>
                        </Td>
                        <Td>
                          <StatusBadge status={s.status} />
                          {s.status_reason && <div className="mt-0.5 max-w-48 truncate text-xs text-muted" title={s.status_reason}>{s.status_reason}</div>}
                        </Td>
                        <Td className="text-sm">
                          {s.site || "–"}
                          <div className="text-xs text-muted">{[s.building && `Bldg ${s.building}`, s.floor && `Floor ${s.floor}`, s.department].filter(Boolean).join(" · ")}</div>
                        </Td>
                        {mode === "pro" && (
                          <Td className="text-xs">
                            {s.product_number || "–"}
                            {s.product_number && !s.model_verified && <div className="text-muted">hardware not validated</div>}
                          </Td>
                        )}
                        {mode === "pro" && <Td className="font-mono text-xs">{s.firmware || "–"}</Td>}
                        <Td className="w-24">
                          <div className="tabular text-xs">{fmtPct(s.metrics?.cpu_pct)}</div>
                          <Meter value={s.metrics?.cpu_pct} />
                        </Td>
                        <Td className="w-24">
                          <div className="tabular text-xs">{fmtPct(s.metrics?.mem_pct)}</div>
                          <Meter value={s.metrics?.mem_pct} />
                        </Td>
                        <Td className="tabular text-xs">
                          {s.metrics?.poe_budget_w ? `${fmtWatts(s.metrics.poe_consumed_w)} / ${fmtWatts(s.metrics.poe_budget_w)}` : "–"}
                        </Td>
                        <Td className="text-xs">
                          {relTime(s.last_success_at)} <StaleBadge at={s.metrics?.at ?? s.last_success_at} stale={s.poll_stale} />
                        </Td>
                        {can("switch.manage") && (
                          <Td>
                            <Button size="sm" variant="ghost" title="Poll now" aria-label={`Poll ${s.hostname} now`} onClick={() => pollNow(s.id)}>
                              <RefreshCw className="h-4 w-4" />
                            </Button>
                          </Td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </Table>
                <Pagination page={page} pageSize={pageSize} total={d.total} onPage={setPage} />
              </>
            )
          }
        </Loadable>
      </Card>

      <Modal open={adding} onClose={() => setAdding(false)} title="Add switch" wide>
        <SwitchForm
          onCancel={() => setAdding(false)}
          onSaved={(sw) => {
            setAdding(false);
            toast("ok", `${sw.hostname} added. Configure its credentials next.`);
            router.push(`/switches/${sw.id}`);
          }}
        />
      </Modal>
      <DiscoverDialog open={discover} onClose={() => setDiscover(false)} onAdded={() => mutate()} />
      <ChangeDialog request={change} onClose={() => setChange(null)} onCreated={() => setSelected(new Set())} />
    </div>
  );
}
