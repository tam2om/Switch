"use client";

import { useState } from "react";
import { Badge, Button, Card, Checkbox, ErrorBox, Field, Input, Loadable, Modal, Notice, PageHeader, Table, Td, Th, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Integration } from "@/lib/types";

interface PreviewItem {
  external_id: string;
  name: string;
  ip: string | null;
  model: string | null;
  matched_switch_id: number | null;
  url: string;
}

const INFO: Record<Integration["kind"], { title: string; text: string; userHint: string; secretLabel: string; urlHint: string }> = {
  zabbix: {
    title: "Zabbix",
    text: "Links switches to Zabbix hosts by management IP and shows deep links. Read-only: nothing is written to Zabbix.",
    userHint: "Not used with API tokens",
    secretLabel: "API token",
    urlHint: "Base URL, e.g. https://zabbix.example.internal",
  },
  airwave: {
    title: "Aruba AirWave",
    text: "Imports switch records from AirWave and links them by management IP. Read-only: nothing is written to AirWave.",
    userHint: "AirWave operator account",
    secretLabel: "Password",
    urlHint: "Base URL, e.g. https://airwave.example.internal",
  },
};

function IntegrationCard({ it, onChanged }: { it: Integration; onChanged: () => void }) {
  const toast = useToast();
  const info = INFO[it.kind];
  const [f, setF] = useState({
    enabled: it.enabled,
    url: it.url,
    username: it.username,
    secret: "",
    verify_tls: it.verify_tls,
    host_group: String((it.params as { host_group?: string }).host_group || ""),
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [preview, setPreview] = useState<PreviewItem[] | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const run = async (name: string, fn: () => Promise<void>) => {
    setBusy(name);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run("save", async () => {
      await api(`/integrations/${it.kind}`, {
        method: "PUT",
        body: {
          enabled: f.enabled,
          url: f.url,
          username: f.username,
          secret: f.secret || null,
          verify_tls: f.verify_tls,
          params: it.kind === "zabbix" && f.host_group ? { host_group: f.host_group } : {},
        },
      });
      setF({ ...f, secret: "" });
      toast("ok", `${info.title} settings saved`);
      onChanged();
    });

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {info.title} {it.enabled ? <Badge tone="ok">enabled</Badge> : <Badge>disabled</Badge>}
        </span>
      }
    >
      <div className="space-y-3">
        <p className="text-sm text-muted">{info.text}</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="URL" htmlFor={`${it.kind}-url`} hint={info.urlHint}>
            <Input id={`${it.kind}-url`} value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} />
          </Field>
          <Field label="Username" htmlFor={`${it.kind}-user`} hint={info.userHint}>
            <Input id={`${it.kind}-user`} value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" />
          </Field>
          <Field label={info.secretLabel} htmlFor={`${it.kind}-secret`} hint={it.has_secret ? "A secret is stored. Leave empty to keep it." : "Stored encrypted."}>
            <Input id={`${it.kind}-secret`} type="password" autoComplete="new-password" value={f.secret} onChange={(e) => setF({ ...f, secret: e.target.value })} />
          </Field>
          {it.kind === "zabbix" && (
            <Field label="Host group (optional)" htmlFor="zbx-group">
              <Input id="zbx-group" value={f.host_group} onChange={(e) => setF({ ...f, host_group: e.target.value })} />
            </Field>
          )}
        </div>
        <div className="flex flex-wrap gap-6">
          <Checkbox label="Enabled" checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} />
          <Checkbox label="Verify TLS certificate" checked={f.verify_tls} onChange={(v) => setF({ ...f, verify_tls: v })} />
        </div>
        {!f.verify_tls && <Notice tone="warn">TLS verification is off. Only use this for testing with self-signed certificates.</Notice>}
        <p className="text-xs text-muted">
          Last sync {relTime(it.last_sync_at)} · status {it.last_status}
          {it.last_message && ` · ${it.last_message}`}
        </p>
        <ErrorBox error={err} />
        {result && <Notice tone="info">{result}</Notice>}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" loading={busy === "save"} onClick={save}>Save</Button>
          <Button
            loading={busy === "test"}
            onClick={() =>
              run("test", async () => {
                const r = await api<Record<string, unknown>>(`/integrations/${it.kind}/test`, { method: "POST" });
                setResult(r.ok ? `Connection OK: ${Object.entries(r).filter(([k]) => k !== "ok").map(([k, v]) => `${k} ${v}`).join(", ")}` : `Connection failed: ${r.error}`);
              })
            }
          >
            Test connection
          </Button>
          <Button loading={busy === "preview"} onClick={() => run("preview", async () => setPreview(await api<PreviewItem[]>(`/integrations/${it.kind}/preview`)))}>
            Preview devices
          </Button>
          <Button
            loading={busy === "sync"}
            onClick={() =>
              run("sync", async () => {
                const r = await api<Record<string, unknown>>(`/integrations/${it.kind}/sync`, { method: "POST" });
                setResult(r.error ? `Sync failed: ${r.error}` : r.skipped ? `Sync skipped: ${r.skipped}` : `Sync done: ${r.linked} linked, ${r.problems ?? 0} problem(s), ${r.seen} seen`);
                onChanged();
              })
            }
          >
            Link by IP
          </Button>
        </div>
      </div>
      <Modal open={!!preview} wide title={`${info.title} devices`} onClose={() => setPreview(null)} footer={
        <>
          <Button onClick={() => setPreview(null)}>Close</Button>
          <Button
            variant="primary"
            loading={busy === "import"}
            disabled={!preview?.some((p) => !p.matched_switch_id)}
            onClick={() =>
              run("import", async () => {
                const r = await api<Record<string, unknown>>(`/integrations/${it.kind}/sync`, { method: "POST", query: { import_new: true } });
                setResult(r.error ? `Import failed: ${r.error}` : `Imported ${Array.isArray(r.imported) ? r.imported.length : r.imported} new switch(es), linked ${r.linked}. Imported switches need credentials before they can be monitored.`);
                setPreview(null);
                onChanged();
              })
            }
          >
            Import unmatched as new switches
          </Button>
        </>
      }>
        {preview && (preview.length === 0 ? <p className="text-sm text-muted">No switches found.</p> : (
          <Table>
            <thead><tr><Th>Name</Th><Th>IP</Th><Th>Model</Th><Th>In inventory</Th></tr></thead>
            <tbody>
              {preview.map((p) => (
                <tr key={p.external_id}>
                  <Td><a href={p.url} target="_blank" rel="noreferrer noopener" className="text-accent hover:underline">{p.name}</a></Td>
                  <Td className="font-mono text-xs">{p.ip || "–"}</Td>
                  <Td className="text-xs">{p.model || "–"}</Td>
                  <Td>{p.matched_switch_id ? <Badge tone="ok">matched</Badge> : <Badge>new</Badge>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        ))}
      </Modal>
    </Card>
  );
}

export default function IntegrationsPage() {
  const { data, error, mutate } = useApi<Integration[]>("/integrations");
  return (
    <div>
      <PageHeader title="Integrations" subtitle="Optional read-only links to existing monitoring and management systems" />
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) => (
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            {rows.map((it) => <IntegrationCard key={`${it.kind}-${it.last_sync_at}-${it.has_secret}`} it={it} onChanged={() => mutate()} />)}
          </div>
        )}
      </Loadable>
      <p className="mt-4 text-xs text-muted">
        These integrations have been tested against API simulations only. Validate them against your Zabbix and AirWave servers before relying on them.
      </p>
    </div>
  );
}
