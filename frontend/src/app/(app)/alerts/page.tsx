"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Button, Card, Checkbox, Empty, ErrorBox, Field, Input, Loadable, Modal, PageHeader, Pagination, Select, StatusBadge, Table, Tabs, Td, Th, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Alert, EventRow, Page } from "@/lib/types";

interface Rule {
  id: number;
  type: string;
  name: string;
  enabled: boolean;
  severity: string;
  threshold: number | null;
  notify_email: boolean;
  recipients: string[];
}

function AlertsTab() {
  const { can } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState("active");
  const [severity, setSeverity] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useApi<Page<Alert>>("/alerts", { status, severity, page, page_size: 100 }, { live: true });
  const act = async (a: Alert, action: "ack" | "resolve") => {
    try {
      await api(`/alerts/${a.id}/${action}`, { method: "POST" });
      mutate();
    } catch (e) {
      toast("bad", errorMessage(e));
    }
  };
  return (
    <Card bodyClassName="p-0">
      <div className="flex flex-wrap gap-2 border-b border-line p-3">
        <Select aria-label="Status" className="w-40" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
          <option value="active">Active</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="">All</option>
        </Select>
        <Select aria-label="Severity" className="w-36" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}>
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </Select>
      </div>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) =>
          d.items.length === 0 ? (
            <Empty>No alerts.</Empty>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Severity</Th>
                    <Th>Alert</Th>
                    <Th>Switch</Th>
                    <Th>First seen</Th>
                    <Th>Last seen</Th>
                    <Th>Count</Th>
                    <Th>Status</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((a) => (
                    <tr key={a.id}>
                      <Td><StatusBadge status={a.severity} /></Td>
                      <Td>
                        {a.message}
                        <div className="text-xs text-muted">{a.type.replace(/_/g, " ")}</div>
                      </Td>
                      <Td>{a.switch_id ? <Link href={`/switches/${a.switch_id}${a.port_name ? `?tab=ports&port=${encodeURIComponent(a.port_name)}` : ""}`} className="hover:text-accent">{a.hostname}{a.port_name ? ` · ${a.port_name}` : ""}</Link> : "–"}</Td>
                      <Td className="whitespace-nowrap text-xs">{fmtDate(a.first_seen)}</Td>
                      <Td className="whitespace-nowrap text-xs">{relTime(a.last_seen)}</Td>
                      <Td className="tabular">{a.occurrences}</Td>
                      <Td><Badge tone={a.status === "active" ? "warn" : a.status === "resolved" ? "ok" : "info"}>{a.status}</Badge></Td>
                      <Td className="whitespace-nowrap text-right">
                        {can("alert.ack") && a.status === "active" && <Button size="sm" variant="ghost" onClick={() => act(a, "ack")}>Acknowledge</Button>}
                        {can("alert.ack") && a.status !== "resolved" && <Button size="sm" variant="ghost" onClick={() => act(a, "resolve")}>Resolve</Button>}
                      </Td>
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

function EventsTab() {
  const [severity, setSeverity] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const { data, error, mutate } = useApi<Page<EventRow>>("/events", { severity, type_prefix: type, page, page_size: 100 }, { live: true });
  return (
    <Card bodyClassName="p-0">
      <div className="flex flex-wrap gap-2 border-b border-line p-3">
        <Select aria-label="Severity" className="w-36" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(1); }}>
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </Select>
        <Input className="w-56" placeholder="Type prefix, e.g. port." aria-label="Event type" value={type} onChange={(e) => { setType(e.target.value); setPage(1); }} />
      </div>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(d) =>
          d.items.length === 0 ? (
            <Empty>No events.</Empty>
          ) : (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Time</Th>
                    <Th>Severity</Th>
                    <Th>Type</Th>
                    <Th>Switch</Th>
                    <Th>Message</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((e) => (
                    <tr key={e.id}>
                      <Td className="whitespace-nowrap text-xs">{fmtDate(e.ts)}</Td>
                      <Td><StatusBadge status={e.severity} /></Td>
                      <Td className="text-xs text-muted">{e.type}</Td>
                      <Td>{e.switch_id ? <Link href={`/switches/${e.switch_id}?tab=events`} className="hover:text-accent">{e.hostname}</Link> : "–"}</Td>
                      <Td>{e.message}</Td>
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

function RuleEditor({ rule, onClose, onSaved }: { rule: Rule; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    enabled: rule.enabled,
    severity: rule.severity,
    threshold: rule.threshold === null ? "" : String(rule.threshold),
    notify_email: rule.notify_email,
    recipients: rule.recipients.join(", "),
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api(`/alert-rules/${rule.id}`, {
        method: "PATCH",
        body: {
          enabled: f.enabled,
          severity: f.severity,
          threshold: f.threshold === "" ? null : Number(f.threshold),
          notify_email: f.notify_email,
          recipients: f.recipients.split(/[\s,;]+/).filter(Boolean),
        },
      });
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open title={`Alert rule: ${rule.name}`} onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save</Button></>}>
      <div className="space-y-3">
        <Checkbox label="Enabled" checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} />
        <div className="grid grid-cols-2 gap-3">
          <Field label="Severity" htmlFor="r-sev">
            <Select id="r-sev" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>
              <option value="critical">Critical</option>
              <option value="warning">Warning</option>
              <option value="info">Info</option>
            </Select>
          </Field>
          {rule.threshold !== null && (
            <Field label="Threshold" htmlFor="r-th">
              <Input id="r-th" type="number" value={f.threshold} onChange={(e) => setF({ ...f, threshold: e.target.value })} />
            </Field>
          )}
        </div>
        <Checkbox label="Send email notifications" checked={f.notify_email} onChange={(v) => setF({ ...f, notify_email: v })} />
        <Field label="Recipients" htmlFor="r-rcpt" hint="Comma separated email addresses. SMTP must be configured on the server.">
          <Input id="r-rcpt" value={f.recipients} onChange={(e) => setF({ ...f, recipients: e.target.value })} disabled={!f.notify_email} />
        </Field>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

function RulesTab() {
  const { can } = useAuth();
  const toast = useToast();
  const { data, error, mutate } = useApi<Rule[]>("/alert-rules");
  const [edit, setEdit] = useState<Rule | null>(null);
  return (
    <Card bodyClassName="p-0">
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rules) => (
          <Table>
            <thead>
              <tr>
                <Th>Rule</Th>
                <Th>Enabled</Th>
                <Th>Severity</Th>
                <Th>Threshold</Th>
                <Th>Email</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <Td>{r.name}<div className="text-xs text-muted">{r.type}</div></Td>
                  <Td>{r.enabled ? <Badge tone="ok">on</Badge> : <Badge>off</Badge>}</Td>
                  <Td><StatusBadge status={r.severity} /></Td>
                  <Td className="tabular">{r.threshold ?? "–"}</Td>
                  <Td className="text-xs">{r.notify_email ? r.recipients.join(", ") || "no recipients" : "–"}</Td>
                  <Td className="text-right">{can("alert_rule.manage") && <Button size="sm" variant="ghost" onClick={() => setEdit(r)}>Edit</Button>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Loadable>
      {edit && <RuleEditor rule={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("ok", "Rule saved"); mutate(); }} />}
    </Card>
  );
}

type Tab = "alerts" | "events" | "rules";

function AlertsPage() {
  const { can } = useAuth();
  const params = useSearchParams();
  const initial = (params.get("tab") as Tab) || (can("alert.view") ? "alerts" : "events");
  const [tab, setTab] = useState<Tab>(initial);
  return (
    <div>
      <PageHeader title="Alerts & events" />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "alerts", label: "Alerts", hidden: !can("alert.view") },
          { id: "events", label: "Events", hidden: !can("event.view") },
          { id: "rules", label: "Alert rules", hidden: !can("alert.view") },
        ]}
      />
      {tab === "alerts" && <AlertsTab />}
      {tab === "events" && <EventsTab />}
      {tab === "rules" && <RulesTab />}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <AlertsPage />
    </Suspense>
  );
}
