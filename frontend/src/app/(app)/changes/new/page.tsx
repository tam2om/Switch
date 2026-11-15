"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { ChangeDialog, type ChangeRequest } from "@/components/ChangeDialog";
import type { Values } from "@/components/SchemaForm";
import { Badge, Button, Card, Checkbox, Input, Loadable, Notice, PageHeader, Select, SimBadge, StatusBadge } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import type { Group, Operation, Page, Site, SwitchRow } from "@/lib/types";

interface Template {
  id: number;
  name: string;
  operation: string;
  params: Values;
}

function Wizard() {
  const params = useSearchParams();
  const router = useRouter();
  const { can } = useAuth();
  const ops = useApi<Operation[]>("/operations");
  const groups = useApi<Group[]>("/groups");
  const sites = useApi<Site[]>("/sites");
  const switches = useApi<Page<SwitchRow>>("/switches", { page_size: 500 });
  const templateId = params.get("template");
  const templates = useApi<Template[]>(templateId ? "/templates" : null);
  const template = templates.data?.find((t) => String(t.id) === templateId);

  const [operation, setOperation] = useState(params.get("operation") || "");
  const [selected, setSelected] = useState<Set<number>>(
    new Set((params.get("switches") || "").split(",").filter(Boolean).map(Number)),
  );
  const [q, setQ] = useState("");
  const [siteFilter, setSiteFilter] = useState("");
  const [onlyOnline, setOnlyOnline] = useState(true);
  const [request, setRequest] = useState<ChangeRequest | null>(null);

  const opName = template?.operation || operation;
  const op = ops.data?.find((o) => o.name === opName);
  const bulkOps = (ops.data || []).filter((o) => o.bulk && o.allowed);

  const visible = useMemo(
    () =>
      (switches.data?.items || []).filter(
        (s) =>
          (!q || s.hostname.toLowerCase().includes(q.toLowerCase()) || s.mgmt_ip.includes(q)) &&
          (!siteFilter || String(s.site_id) === siteFilter) &&
          (!onlyOnline || s.status === "online"),
      ),
    [switches.data, q, siteFilter, onlyOnline],
  );

  const toggle = (id: number) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });

  const initialParams = (): Values => {
    if (template) return template.params;
    const p: Values = {};
    if (params.get("vlan_id")) p.vlan_id = Number(params.get("vlan_id"));
    if (params.get("name")) p.name = params.get("name");
    return p;
  };

  if (!can("bulk.execute")) return <Notice tone="bad">Your role cannot run bulk changes.</Notice>;

  const simCount = (switches.data?.items || []).filter((s) => selected.has(s.id) && s.is_simulated).length;

  return (
    <div>
      <PageHeader title="Bulk change" subtitle="Apply one reviewed change to many switches in controlled batches" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[360px_1fr]">
        <Card title="1. What to change">
          {template ? (
            <div className="space-y-2 text-sm">
              <p>
                Template <strong>{template.name}</strong> <Badge>{template.operation}</Badge>
              </p>
              <Button size="sm" variant="ghost" onClick={() => router.replace("/changes/new")}>Choose an operation instead</Button>
            </div>
          ) : (
            <Loadable data={ops.data} error={ops.error}>
              {() => (
                <div className="space-y-1">
                  {bulkOps.map((o) => (
                    <label key={o.name} className={`flex cursor-pointer items-start gap-2 rounded-md border p-2 text-sm ${operation === o.name ? "border-accent bg-accent/10" : "border-line hover:bg-panel-2"}`}>
                      <input type="radio" name="op" className="mt-0.5" checked={operation === o.name} onChange={() => setOperation(o.name)} />
                      <span>
                        {o.title}
                        {o.warning && <span className="block text-xs text-warn">{o.warning}</span>}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </Loadable>
          )}
        </Card>

        <Card
          title={`2. Target switches (${selected.size} selected)`}
          actions={
            <Button variant="primary" disabled={!op || selected.size === 0} onClick={() => setRequest({ operation: opName, switchIds: [...selected], params: initialParams(), templateId: template?.id })}>
              3. Parameters and impact review…
            </Button>
          }
        >
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <Input className="w-56" placeholder="Filter by hostname or IP" aria-label="Filter switches" value={q} onChange={(e) => setQ(e.target.value)} />
            <Select className="w-44" aria-label="Site" value={siteFilter} onChange={(e) => setSiteFilter(e.target.value)}>
              <option value="">All sites</option>
              {sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
            <Checkbox label="Online only" checked={onlyOnline} onChange={setOnlyOnline} />
            <Select
              className="w-48"
              aria-label="Add group"
              value=""
              onChange={(e) => {
                const g = groups.data?.find((x) => String(x.id) === e.target.value);
                if (g) setSelected((s) => new Set([...s, ...g.switch_ids]));
              }}
            >
              <option value="">Add a group…</option>
              {groups.data?.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.switch_ids.length})</option>)}
            </Select>
            <Button size="sm" onClick={() => setSelected((s) => new Set([...s, ...visible.map((x) => x.id)]))}>Select shown ({visible.length})</Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
          </div>
          {simCount > 0 && (
            <div className="mb-3">
              <Notice tone="sim">{simCount} of the selected switches are simulated. Changes to them only affect the simulator.</Notice>
            </div>
          )}
          <Loadable data={switches.data} error={switches.error}>
            {() => (
              <div className="grid max-h-[60vh] grid-cols-1 gap-1 overflow-y-auto sm:grid-cols-2 2xl:grid-cols-3">
                {visible.map((s) => (
                  <label key={s.id} className={`flex cursor-pointer items-center gap-2 rounded border px-2 py-1.5 text-sm ${selected.has(s.id) ? "border-accent bg-accent/5" : "border-line"}`}>
                    <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggle(s.id)} aria-label={`Select ${s.hostname}`} />
                    <span className="flex-1 truncate">{s.hostname}</span>
                    <SimBadge show={s.is_simulated} />
                    <StatusBadge status={s.status} />
                  </label>
                ))}
              </div>
            )}
          </Loadable>
        </Card>
      </div>
      <ChangeDialog request={request} onClose={() => setRequest(null)} onCreated={(job) => router.push(`/changes/${job.id}`)} />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Wizard />
    </Suspense>
  );
}
