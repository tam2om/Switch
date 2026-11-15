"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { defaultsFor, SchemaForm, type Values } from "@/components/SchemaForm";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorBox, Field, Input, Loadable, Modal, PageHeader, Pagination, RiskBadge, Select, StatusBadge, Table, Tabs, Td, Th, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Job, Operation, Page } from "@/lib/types";

interface Template {
  id: number;
  name: string;
  description: string;
  operation: string;
  params: Values;
  created_at: string;
  updated_at: string;
}

function JobsTable({ status, live }: { status: string; live?: boolean }) {
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState(status);
  const { data, error, mutate } = useApi<Page<Job>>("/jobs", { status: filter, page, page_size: 50 }, { live: live ?? true });
  return (
    <Card bodyClassName="p-0">
      {status !== "pending_approval" && (
        <div className="border-b border-line p-3">
          <Select aria-label="Status" className="w-48" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {["pending_approval", "queued", "running", "completed", "partial", "failed", "cancelled", "rejected"].map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </Select>
        </div>
      )}
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) =>
          d.items.length === 0 ? (
            <Empty>{status === "pending_approval" ? "Nothing is waiting for approval." : "No changes."}</Empty>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>#</Th>
                    <Th>Change</Th>
                    <Th>Risk</Th>
                    <Th>Status</Th>
                    <Th>Progress</Th>
                    <Th>Requested by</Th>
                    <Th>Created</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((j) => {
                    const done = (j.progress.success || 0) + (j.progress.failed || 0) + (j.progress.verify_failed || 0) + (j.progress.skipped || 0) + (j.progress.cancelled || 0);
                    return (
                      <tr key={j.id} className="hover:bg-panel-2/50">
                        <Td className="tabular">{j.id}</Td>
                        <Td>
                          <Link href={`/changes/${j.id}`} className="font-medium hover:text-accent">{j.title}</Link>
                          <div className="text-xs text-muted">{j.operation}</div>
                        </Td>
                        <Td><RiskBadge risk={j.risk} /></Td>
                        <Td><StatusBadge status={j.status} /></Td>
                        <Td className="tabular text-xs">
                          {done}/{j.target_count}
                          {(j.progress.failed || 0) + (j.progress.verify_failed || 0) > 0 && <span className="text-bad"> · {(j.progress.failed || 0) + (j.progress.verify_failed || 0)} failed</span>}
                        </Td>
                        <Td>{j.requested_by}</Td>
                        <Td className="whitespace-nowrap text-xs" >{relTime(j.created_at)}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
              <Pagination page={page} pageSize={50} total={d.total} onPage={setPage} />
            </>
          )
        }
      </Loadable>
    </Card>
  );
}

function TemplateEditor({ initial, ops, onClose, onSaved }: { initial: Template | "new"; ops: Operation[]; onClose: () => void; onSaved: () => void }) {
  const t = initial === "new" ? null : initial;
  const [name, setName] = useState(t?.name || "");
  const [description, setDescription] = useState(t?.description || "");
  const [operation, setOperation] = useState(t?.operation || "");
  const op = ops.find((o) => o.name === operation);
  const [values, setValues] = useState<Values>(t?.params || {});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body = { name, description, operation, params: values };
      if (t) await api(`/templates/${t.id}`, { method: "PUT", body });
      else await api("/templates", { method: "POST", body });
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open wide title={t ? `Edit template ${t.name}` : "New template"} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save} disabled={!name || !operation}>Save template</Button></>}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Name" htmlFor="t-name"><Input id="t-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Operation" htmlFor="t-op">
            <Select id="t-op" value={operation} disabled={!!t} onChange={(e) => { setOperation(e.target.value); const o = ops.find((x) => x.name === e.target.value); setValues(o ? defaultsFor(o.schema) : {}); }}>
              <option value="">Select…</option>
              {ops.filter((o) => o.bulk).map((o) => <option key={o.name} value={o.name}>{o.title}</option>)}
            </Select>
          </Field>
        </div>
        <Field label="Description" htmlFor="t-desc"><Input id="t-desc" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
        {op && <SchemaForm schema={op.schema} values={values} onChange={setValues} />}
        <p className="text-xs text-muted">Secrets in templates are stored encrypted and never shown again; leave them as ******** to keep the stored value.</p>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function TemplatesTab() {
  const { can } = useAuth();
  const router = useRouter();
  const toast = useToast();
  const { data, error, mutate } = useApi<Template[]>("/templates");
  const ops = useApi<Operation[]>("/operations");
  const [edit, setEdit] = useState<Template | "new" | null>(null);
  const [del, setDel] = useState<Template | null>(null);
  return (
    <Card title="Configuration templates" bodyClassName="p-0" actions={can("template.manage") && <Button size="sm" variant="primary" onClick={() => setEdit("new")}>New template</Button>}>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No templates. Templates store a reviewed set of parameters that can be applied to many switches.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Name</Th>
                  <Th>Operation</Th>
                  <Th>Parameters</Th>
                  <Th>Updated</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {rows.map((t) => (
                  <tr key={t.id}>
                    <Td className="font-medium">{t.name}<div className="text-xs text-muted">{t.description}</div></Td>
                    <Td>{t.operation}</Td>
                    <Td className="max-w-80 truncate font-mono text-xs">{JSON.stringify(t.params)}</Td>
                    <Td className="text-xs">{fmtDate(t.updated_at)}</Td>
                    <Td className="whitespace-nowrap text-right">
                      {can("bulk.execute") && <Button size="sm" variant="ghost" onClick={() => router.push(`/changes/new?template=${t.id}`)}>Apply…</Button>}
                      {can("template.manage") && <Button size="sm" variant="ghost" onClick={() => setEdit(t)}>Edit</Button>}
                      {can("template.manage") && <Button size="sm" variant="ghost" onClick={() => setDel(t)}>Delete</Button>}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )
        }
      </Loadable>
      {edit && ops.data && <TemplateEditor initial={edit} ops={ops.data} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("ok", "Template saved"); mutate(); }} />}
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} danger title="Delete template" message={`Delete template "${del?.name}"?`} confirmLabel="Delete" onConfirm={async () => { await api(`/templates/${del!.id}`, { method: "DELETE" }); mutate(); }} />
    </Card>
  );
}

type Tab = "pending" | "all" | "templates";

export default function ChangesPage() {
  const { can } = useAuth();
  const pending = useApi<Page<Job>>("/jobs", { status: "pending_approval", page_size: 1 }, { live: true });
  const [tab, setTab] = useState<Tab>(pending.data?.total ? "pending" : "all");
  return (
    <div>
      <PageHeader
        title="Changes & approvals"
        subtitle="Every configuration change runs as an audited job with pre-change backup, verification and rollback information"
        actions={can("bulk.execute") && <Link href="/changes/new" className="inline-flex h-9 items-center rounded-md bg-accent px-3 text-sm font-medium text-accent-fg">New bulk change</Link>}
      />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "pending", label: `Waiting for approval${pending.data?.total ? ` (${pending.data.total})` : ""}` },
          { id: "all", label: "All changes" },
          { id: "templates", label: "Templates" },
        ]}
      />
      {tab === "pending" && <JobsTable status="pending_approval" />}
      {tab === "all" && <JobsTable status="" />}
      {tab === "templates" && <TemplatesTab />}
      {pending.data?.total && tab !== "pending" ? (
        <p className="mt-3 text-sm">
          <Badge tone="warn">{pending.data.total}</Badge> change(s) are waiting for approval.
        </p>
      ) : null}
    </div>
  );
}
