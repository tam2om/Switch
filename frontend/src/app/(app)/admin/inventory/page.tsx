"use client";

import { useState } from "react";
import { fmtDate } from "@/lib/format";
import { Button, Card, Checkbox, ConfirmDialog, Empty, ErrorBox, Field, Input, Loadable, Modal, PageHeader, Table, Td, Th, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import type { Group, Page, Site, SwitchRow } from "@/lib/types";

interface SwitchModel {
  id: number;
  product_number: string;
  name: string;
  family: string;
  access_ports: number;
  uplink_ports: number;
  poe_budget_w: number | null;
  hardware_verified: boolean;
  hardware_evidence: Record<string, { at: string; hostname: string; firmware: string; passed: number; failed: number }>;
  verified_operations: string[];
}

function SiteEditor({ site, onClose, onSaved }: { site: Site | "new"; onClose: () => void; onSaved: () => void }) {
  const s = site === "new" ? null : site;
  const [f, setF] = useState({ name: s?.name || "", address: s?.address || "", description: s?.description || "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api(s ? `/sites/${s.id}` : "/sites", { method: s ? "PATCH" : "POST", body: f });
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open title={s ? `Edit site ${s.name}` : "New site"} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save</Button></>}>
      <div className="space-y-3">
        <Field label="Name" htmlFor="s-name"><Input id="s-name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Address" htmlFor="s-addr"><Input id="s-addr" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} /></Field>
        <Field label="Description" htmlFor="s-desc"><Input id="s-desc" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function GroupEditor({ group, switches, onClose, onSaved }: { group: Group | "new"; switches: SwitchRow[]; onClose: () => void; onSaved: () => void }) {
  const g = group === "new" ? null : group;
  const [name, setName] = useState(g?.name || "");
  const [description, setDescription] = useState(g?.description || "");
  const [members, setMembers] = useState<Set<number>>(new Set(g?.switch_ids || []));
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api(g ? `/groups/${g.id}` : "/groups", { method: g ? "PATCH" : "POST", body: { name, description, switch_ids: [...members] } });
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const shown = switches.filter((s) => s.hostname.toLowerCase().includes(q.toLowerCase()));
  return (
    <Modal open wide title={g ? `Edit group ${g.name}` : "New group"} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save</Button></>}>
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="g-name"><Input id="g-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Description" htmlFor="g-desc"><Input id="g-desc" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        </div>
        <div className="flex items-center gap-2">
          <Input className="w-64" placeholder="Filter switches" aria-label="Filter switches" value={q} onChange={(e) => setQ(e.target.value)} />
          <span className="text-sm text-muted">{members.size} member(s)</span>
          <Button size="sm" onClick={() => setMembers(new Set([...members, ...shown.map((s) => s.id)]))}>Add shown</Button>
          <Button size="sm" variant="ghost" onClick={() => setMembers(new Set())}>Clear</Button>
        </div>
        <div className="grid max-h-72 grid-cols-2 gap-1 overflow-y-auto md:grid-cols-3">
          {shown.map((s) => (
            <Checkbox
              key={s.id}
              label={s.hostname}
              checked={members.has(s.id)}
              onChange={(v) => {
                const n = new Set(members);
                if (v) n.add(s.id);
                else n.delete(s.id);
                setMembers(n);
              }}
            />
          ))}
        </div>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

export default function InventoryAdmin() {
  const { can } = useAuth();
  const toast = useToast();
  const sites = useApi<Site[]>("/sites");
  const groups = useApi<Group[]>("/groups");
  const models = useApi<SwitchModel[]>("/models");
  const switches = useApi<Page<SwitchRow>>("/switches", { page_size: 500 });
  const [site, setSite] = useState<Site | "new" | null>(null);
  const [group, setGroup] = useState<Group | "new" | null>(null);
  const [delSite, setDelSite] = useState<Site | null>(null);
  const [delGroup, setDelGroup] = useState<Group | null>(null);
  const manage = can("switch.manage");
  return (
    <div className="space-y-4">
      <PageHeader title="Sites & groups" subtitle="Organise switches for filtering, reporting and bulk changes" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card title="Sites" bodyClassName="p-0" actions={manage && <Button size="sm" variant="primary" onClick={() => setSite("new")}>New site</Button>}>
          <Loadable data={sites.data} error={sites.error}>
            {(rows) =>
              rows.length === 0 ? <Empty>No sites.</Empty> : (
                <Table>
                  <thead><tr><Th>Name</Th><Th>Switches</Th><Th /></tr></thead>
                  <tbody>
                    {rows.map((s) => (
                      <tr key={s.id}>
                        <Td>{s.name}<div className="text-xs text-muted">{[s.address, s.description].filter(Boolean).join(" · ")}</div></Td>
                        <Td className="tabular">{s.switch_count}</Td>
                        <Td className="whitespace-nowrap text-right">
                          {manage && <Button size="sm" variant="ghost" onClick={() => setSite(s)}>Edit</Button>}
                          {manage && <Button size="sm" variant="ghost" onClick={() => setDelSite(s)}>Delete</Button>}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )
            }
          </Loadable>
        </Card>
        <Card title="Groups" bodyClassName="p-0" actions={manage && <Button size="sm" variant="primary" onClick={() => setGroup("new")}>New group</Button>}>
          <Loadable data={groups.data} error={groups.error}>
            {(rows) =>
              rows.length === 0 ? <Empty>No groups.</Empty> : (
                <Table>
                  <thead><tr><Th>Name</Th><Th>Members</Th><Th /></tr></thead>
                  <tbody>
                    {rows.map((g) => (
                      <tr key={g.id}>
                        <Td>{g.name}<div className="text-xs text-muted">{g.description}</div></Td>
                        <Td className="tabular">{g.switch_ids.length}</Td>
                        <Td className="whitespace-nowrap text-right">
                          {manage && <Button size="sm" variant="ghost" onClick={() => setGroup(g)}>Edit</Button>}
                          {manage && <Button size="sm" variant="ghost" onClick={() => setDelGroup(g)}>Delete</Button>}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )
            }
          </Loadable>
        </Card>
      </div>
      <Card title="Supported switch models" bodyClassName="p-0">
        <Loadable data={models.data} error={models.error}>
          {(rows) => (
            <Table>
              <thead><tr><Th>Product</Th><Th>Name</Th><Th>Ports</Th><Th>PoE budget</Th><Th>Hardware validation</Th></tr></thead>
              <tbody>
                {rows.map((m) => (
                  <tr key={m.id}>
                    <Td className="font-mono">{m.product_number}</Td>
                    <Td>{m.name}</Td>
                    <Td className="text-xs">{m.access_ports} access + {m.uplink_ports} SFP+</Td>
                    <Td>{m.poe_budget_w ? `${m.poe_budget_w} W` : "–"}</Td>
                    <Td className="text-xs">
                      {m.hardware_verified ? (
                        "verified"
                      ) : Object.keys(m.hardware_evidence || {}).length === 0 ? (
                        <span className="text-warn">pending (no physical test yet)</span>
                      ) : (
                        Object.entries(m.hardware_evidence).map(([train, ev]) => (
                          <div key={train} className={ev.failed === 0 ? "text-ok" : "text-warn"}>
                            {train}: read-only checks {ev.passed}/{ev.passed + ev.failed} passed on {ev.hostname} ({ev.firmware}), {fmtDate(ev.at)}
                          </div>
                        ))
                      )}
                      {m.verified_operations?.length > 0 && <div className="text-muted">Changes applied and verified on hardware: {m.verified_operations.join(", ")}</div>}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Loadable>
      </Card>
      {site && <SiteEditor site={site} onClose={() => setSite(null)} onSaved={() => { setSite(null); toast("ok", "Site saved"); sites.mutate(); }} />}
      {group && <GroupEditor group={group} switches={switches.data?.items || []} onClose={() => setGroup(null)} onSaved={() => { setGroup(null); toast("ok", "Group saved"); groups.mutate(); }} />}
      <ConfirmDialog open={!!delSite} onClose={() => setDelSite(null)} danger title="Delete site" message={`Delete site "${delSite?.name}"? Switches stay in the inventory without a site.`} confirmLabel="Delete" onConfirm={async () => { await api(`/sites/${delSite!.id}`, { method: "DELETE" }); sites.mutate(); }} />
      <ConfirmDialog open={!!delGroup} onClose={() => setDelGroup(null)} danger title="Delete group" message={`Delete group "${delGroup?.name}"? Its switches are not affected.`} confirmLabel="Delete" onConfirm={async () => { await api(`/groups/${delGroup!.id}`, { method: "DELETE" }); groups.mutate(); }} />
    </div>
  );
}
