"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  Badge, Button, Card, Checkbox, ConfirmDialog, Empty, ErrorBox, Field, Input, Loadable, Modal, Notice, PageHeader, Select,
  SimBadge, Table, Tabs, Td, Th, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import type { Page, SwitchRow } from "@/lib/types";

interface VlanRow {
  vlan_id: number;
  name: string;
  description: string;
  in_catalogue: boolean;
  is_management: boolean;
  is_voice: boolean;
  switch_count: number;
  names_on_switches: string[];
  name_mismatch: boolean;
}

interface Matrix {
  vlans: number[];
  rows: { switch_id: number; hostname: string; is_simulated: boolean; mgmt_vlan: number | null; cells: Record<string, { name: string; untagged: number; tagged: number }> }[];
}

type Tab = "catalogue" | "matrix" | "consistency" | "compare";

function VlanEditor({ initial, onClose, onSaved }: { initial: VlanRow | null | "new"; onClose: () => void; onSaved: () => void }) {
  const isNew = initial === "new";
  const v = isNew ? null : initial;
  const [f, setF] = useState({
    vlan_id: v ? String(v.vlan_id) : "",
    name: v?.name || "",
    description: v?.description || "",
    is_management: v?.is_management || false,
    is_voice: v?.is_voice || false,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  if (!initial) return null;
  const save = async () => {
    setBusy(true);
    setErr(null);
    const body = { ...f, vlan_id: Number(f.vlan_id) };
    try {
      if (v?.in_catalogue) await api(`/vlans/${v.vlan_id}`, { method: "PUT", body });
      else await api("/vlans", { method: "POST", body });
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      open
      title={isNew ? "Add VLAN to plan" : v?.in_catalogue ? `Edit VLAN ${v.vlan_id}` : `Add VLAN ${v?.vlan_id} to plan`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} onClick={save}>Save</Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-muted">The VLAN plan is the reference used for consistency checks. Saving it does not change any switch.</p>
        <div className="grid grid-cols-2 gap-3">
          <Field label="VLAN ID" htmlFor="v-id">
            <Input id="v-id" type="number" min={1} max={4094} value={f.vlan_id} disabled={!!v?.in_catalogue} onChange={(e) => setF({ ...f, vlan_id: e.target.value })} />
          </Field>
          <Field label="Name" htmlFor="v-name">
            <Input id="v-name" maxLength={32} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          </Field>
        </div>
        <Field label="Description" htmlFor="v-desc">
          <Input id="v-desc" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        </Field>
        <div className="flex gap-6">
          <Checkbox label="Management VLAN" checked={f.is_management} onChange={(x) => setF({ ...f, is_management: x })} />
          <Checkbox label="Voice VLAN" checked={f.is_voice} onChange={(x) => setF({ ...f, is_voice: x })} />
        </div>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function CatalogueTab() {
  const { can } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const { data, error, mutate } = useApi<VlanRow[]>("/vlans");
  const [edit, setEdit] = useState<VlanRow | "new" | null>(null);
  const [del, setDel] = useState<VlanRow | null>(null);
  return (
    <Card
      title="VLANs across the network"
      bodyClassName="p-0"
      actions={can("vlan.manage") && <Button size="sm" variant="primary" onClick={() => setEdit("new")}>Add to plan</Button>}
    >
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No VLANs known yet.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>ID</Th>
                  <Th>Name</Th>
                  <Th>In plan</Th>
                  <Th>Switches</Th>
                  <Th>Names seen</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {rows.map((v) => (
                  <tr key={v.vlan_id}>
                    <Td className="font-medium">
                      {v.vlan_id} {v.is_management && <Badge tone="accent">mgmt</Badge>} {v.is_voice && <Badge tone="info">voice</Badge>}
                    </Td>
                    <Td>
                      {v.name}
                      {v.description && <div className="text-xs text-muted">{v.description}</div>}
                    </Td>
                    <Td>{v.in_catalogue ? <Badge tone="ok">yes</Badge> : <span className="text-xs text-muted">discovered only</span>}</Td>
                    <Td className="tabular">{v.switch_count}</Td>
                    <Td className="text-xs">
                      {v.names_on_switches.join(", ") || "–"} {v.name_mismatch && <Badge tone="warn">name mismatch</Badge>}
                    </Td>
                    <Td className="whitespace-nowrap text-right">
                      {can("vlan.manage") && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => setEdit(v)}>{v.in_catalogue ? "Edit" : "Add to plan"}</Button>
                          {can("bulk.execute") && v.vlan_id !== 1 && (
                            <Button size="sm" variant="ghost" onClick={() => router.push(`/changes/new?operation=vlan_create&vlan_id=${v.vlan_id}&name=${encodeURIComponent(v.name)}`)}>
                              Deploy…
                            </Button>
                          )}
                          {v.in_catalogue && (
                            <Button size="sm" variant="ghost" onClick={() => setDel(v)}>Remove from plan</Button>
                          )}
                        </>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
      {edit && (
        <VlanEditor
          initial={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            toast("ok", "VLAN plan updated");
            mutate();
          }}
        />
      )}
      <ConfirmDialog
        open={!!del}
        onClose={() => setDel(null)}
        title="Remove from VLAN plan"
        message={`VLAN ${del?.vlan_id} will be removed from the plan. Switches are not changed.`}
        confirmLabel="Remove"
        onConfirm={async () => {
          await api(`/vlans/${del!.vlan_id}`, { method: "DELETE" });
          mutate();
        }}
      />
    </Card>
  );
}

function MatrixTab() {
  const { data, error, mutate } = useApi<Matrix>("/vlans/matrix");
  const [q, setQ] = useState("");
  return (
    <Card title="Cross-switch VLAN matrix" bodyClassName="p-0" actions={<Input className="w-56" placeholder="Filter switches" aria-label="Filter switches" value={q} onChange={(e) => setQ(e.target.value)} />}>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(m) =>
          m.rows.length === 0 ? (
            <Empty>No VLAN data.</Empty>
          ) : (
            <div className="max-h-[70vh] overflow-auto">
              <table className="text-sm">
                <thead className="sticky top-0 bg-panel">
                  <tr>
                    <Th className="sticky left-0 bg-panel">Switch</Th>
                    {m.vlans.map((v) => (
                      <Th key={v} className="text-center">{v}</Th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {m.rows
                    .filter((r) => r.hostname.toLowerCase().includes(q.toLowerCase()))
                    .map((r) => (
                      <tr key={r.switch_id}>
                        <Td className="sticky left-0 whitespace-nowrap bg-panel">
                          <Link href={`/switches/${r.switch_id}?tab=vlans`} className="hover:text-accent">{r.hostname}</Link> <SimBadge show={r.is_simulated} />
                        </Td>
                        {m.vlans.map((v) => {
                          const c = r.cells[String(v)];
                          return (
                            <td
                              key={v}
                              className={`border-b border-l border-line/60 px-2 py-1 text-center text-xs ${c ? (v === r.mgmt_vlan ? "bg-accent/15" : "bg-ok/10") : "text-muted"}`}
                              title={c ? `${c.name}: ${c.untagged} untagged, ${c.tagged} tagged` : "not configured"}
                            >
                              {c ? `${c.untagged}U ${c.tagged}T` : "—"}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )
        }
      </Loadable>
      <p className="px-4 py-2 text-xs text-muted">Cells show untagged (U) and tagged (T) member port counts. Highlighted cells are the switch&apos;s management VLAN.</p>
    </Card>
  );
}

function ConsistencyTab() {
  const { data, error, mutate } = useApi<{ plan_size: number; switches: number; consistent: boolean; issues: { switch_id: number; hostname: string; type: string; vlan_id?: number; message: string }[] }>("/vlans/consistency");
  return (
    <Card title="Consistency against the VLAN plan" bodyClassName="p-0">
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) => (
          <div>
            <div className="p-4">
              {d.plan_size === 0 ? (
                <Notice tone="info">The VLAN plan is empty. Add VLANs to the plan on the Catalogue tab to enable consistency checks.</Notice>
              ) : d.consistent ? (
                <Notice tone="info">All {d.switches} switches match the plan of {d.plan_size} VLAN(s).</Notice>
              ) : (
                <Notice tone="warn">{d.issues.filter((i) => i.type !== "no_data").length} inconsistency(ies) across {d.switches} switches.</Notice>
              )}
            </div>
            {d.issues.length > 0 && (
              <Table>
                <thead>
                  <tr>
                    <Th>Switch</Th>
                    <Th>Issue</Th>
                    <Th>Details</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.issues.map((i, n) => (
                    <tr key={n}>
                      <Td><Link href={`/switches/${i.switch_id}?tab=vlans`} className="hover:text-accent">{i.hostname}</Link></Td>
                      <Td><Badge tone={i.type === "no_data" ? "muted" : "warn"}>{i.type.replace(/_/g, " ")}</Badge></Td>
                      <Td>{i.message}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </div>
        )}
      </Loadable>
    </Card>
  );
}

function CompareTab() {
  const sw = useApi<Page<SwitchRow>>("/switches", { page_size: 500 });
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const { data, error } = useApi<{ a: { hostname: string }; b: { hostname: string }; rows: { vlan_id: number; a: string | null; b: string | null; status: string }[] }>(a && b ? "/vlans/compare" : null, { a, b });
  return (
    <Card title="Compare two switches">
      <div className="mb-4 flex flex-wrap gap-3">
        {[
          [a, setA, "First switch"],
          [b, setB, "Second switch"],
        ].map(([val, set, label]) => (
          <Select key={label as string} aria-label={label as string} className="w-64" value={val as string} onChange={(e) => (set as (v: string) => void)(e.target.value)}>
            <option value="">{label as string}…</option>
            {sw.data?.items.map((s) => (
              <option key={s.id} value={s.id}>{s.hostname}</option>
            ))}
          </Select>
        ))}
      </div>
      <ErrorBox error={error} />
      {data && (
        <Table>
          <thead>
            <tr>
              <Th>VLAN</Th>
              <Th>{data.a.hostname}</Th>
              <Th>{data.b.hostname}</Th>
              <Th>Result</Th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r.vlan_id}>
                <Td className="font-medium">{r.vlan_id}</Td>
                <Td>{r.a || <span className="text-muted">—</span>}</Td>
                <Td>{r.b || <span className="text-muted">—</span>}</Td>
                <Td><Badge tone={r.status === "both" ? "ok" : r.status === "name_differs" ? "warn" : "info"}>{r.status.replace(/_/g, " ")}</Badge></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  );
}

export default function VlansPage() {
  const [tab, setTab] = useState<Tab>("catalogue");
  return (
    <div>
      <PageHeader title="VLANs" subtitle="VLAN plan, cross-switch matrix and consistency" />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "catalogue", label: "Catalogue" },
          { id: "matrix", label: "Matrix" },
          { id: "consistency", label: "Consistency" },
          { id: "compare", label: "Compare" },
        ]}
      />
      {tab === "catalogue" && <CatalogueTab />}
      {tab === "matrix" && <MatrixTab />}
      {tab === "consistency" && <ConsistencyTab />}
      {tab === "compare" && <CompareTab />}
    </div>
  );
}
