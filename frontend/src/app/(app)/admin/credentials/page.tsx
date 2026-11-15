"use client";

import { useMemo, useState } from "react";
import { Badge, Button, Card, ConfirmDialog, Empty, ErrorBox, Field, Input, Loadable, Modal, Notice, PageHeader, Select, Table, Td, Th, useToast } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Credential, Page, SwitchRow } from "@/lib/types";

const KIND_LABEL: Record<string, string> = { rest: "REST API", ssh: "SSH", snmpv3: "SNMPv3" };

function CredentialEditor({ switches, preset, onClose, onSaved }: { switches: SwitchRow[]; preset: { switch_id: string; kind?: string; purpose?: string; username?: string }; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    switch_id: preset.switch_id,
    kind: preset.kind || "rest",
    purpose: preset.purpose || "monitor",
    username: preset.username || "",
    password: "",
    auth_password: "",
    priv_password: "",
    auth_protocol: "sha",
    priv_protocol: "aes",
    port: "22",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      const body: Record<string, unknown> = {
        switch_id: f.switch_id ? Number(f.switch_id) : null,
        kind: f.kind,
        purpose: f.kind === "snmpv3" ? "monitor" : f.purpose,
        username: f.username,
      };
      if (f.kind === "snmpv3") Object.assign(body, { auth_password: f.auth_password, priv_password: f.priv_password, auth_protocol: f.auth_protocol, priv_protocol: f.priv_protocol });
      else Object.assign(body, { password: f.password });
      if (f.kind === "ssh") body.port = Number(f.port);
      await api("/credentials", { method: "PUT", body });
      onSaved();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open title="Set device credential" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" loading={busy} onClick={save}>Save encrypted</Button></>}>
      <div className="space-y-3">
        <Notice tone="info">Secrets are encrypted with AES-256-GCM before they are stored and are never shown again. Saving replaces any existing credential of the same kind and purpose.</Notice>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Applies to" htmlFor="c-sw">
            <Select id="c-sw" value={f.switch_id} onChange={(e) => setF({ ...f, switch_id: e.target.value })}>
              <option value="">Fleet default (all switches)</option>
              {switches.map((s) => <option key={s.id} value={s.id}>{s.hostname}</option>)}
            </Select>
          </Field>
          <Field label="Protocol" htmlFor="c-kind">
            <Select id="c-kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
              <option value="rest">REST API (HTTPS)</option>
              <option value="snmpv3">SNMPv3 (monitoring only)</option>
              <option value="ssh">SSH (controlled fallback)</option>
            </Select>
          </Field>
          {f.kind !== "snmpv3" && (
            <Field label="Purpose" htmlFor="c-purpose" hint="Use a read-only operator account for monitoring and a manager account for changes.">
              <Select id="c-purpose" value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })}>
                <option value="monitor">Monitoring (read)</option>
                <option value="config">Configuration (write)</option>
              </Select>
            </Field>
          )}
          <Field label="Username" htmlFor="c-user">
            <Input id="c-user" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} autoComplete="off" />
          </Field>
          {f.kind === "snmpv3" ? (
            <>
              <Field label="Auth protocol" htmlFor="c-ap">
                <Select id="c-ap" value={f.auth_protocol} onChange={(e) => setF({ ...f, auth_protocol: e.target.value })}>
                  <option value="sha">SHA-1 (AOS-S default)</option>
                  <option value="sha256">SHA-256 (if supported by firmware)</option>
                  <option value="sha512">SHA-512 (if supported by firmware)</option>
                </Select>
              </Field>
              <Field label="Auth passphrase" htmlFor="c-apw">
                <Input id="c-apw" type="password" autoComplete="new-password" value={f.auth_password} onChange={(e) => setF({ ...f, auth_password: e.target.value })} />
              </Field>
              <Field label="Privacy protocol" htmlFor="c-pp">
                <Select id="c-pp" value={f.priv_protocol} onChange={(e) => setF({ ...f, priv_protocol: e.target.value })}>
                  <option value="aes">AES-128 (AOS-S default)</option>
                  <option value="aes192">AES-192 (if supported by firmware)</option>
                  <option value="aes256">AES-256 (if supported by firmware)</option>
                </Select>
              </Field>
              <Field label="Privacy passphrase" htmlFor="c-ppw">
                <Input id="c-ppw" type="password" autoComplete="new-password" value={f.priv_password} onChange={(e) => setF({ ...f, priv_password: e.target.value })} />
              </Field>
            </>
          ) : (
            <Field label="Password" htmlFor="c-pw">
              <Input id="c-pw" type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
            </Field>
          )}
          {f.kind === "ssh" && (
            <Field label="SSH port" htmlFor="c-port">
              <Input id="c-port" type="number" min={1} max={65535} value={f.port} onChange={(e) => setF({ ...f, port: e.target.value })} />
            </Field>
          )}
        </div>
        <p className="text-xs text-muted">MD5 and DES are not supported for SNMPv3. Telnet is never used.</p>
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

export default function CredentialsPage() {
  const toast = useToast();
  const { data, error, mutate } = useApi<Credential[]>("/credentials");
  const sw = useApi<Page<SwitchRow>>("/switches", { page_size: 500 });
  const [scope, setScope] = useState("default");
  const [edit, setEdit] = useState<{ switch_id: string; kind?: string; purpose?: string; username?: string } | null>(null);
  const [del, setDel] = useState<Credential | null>(null);
  const names = useMemo(() => Object.fromEntries((sw.data?.items || []).map((s) => [s.id, s.hostname])), [sw.data]);
  const rows = (data || []).filter((c) => (scope === "default" ? c.switch_id === null : scope === "all" ? true : String(c.switch_id) === scope));
  return (
    <div>
      <PageHeader
        title="Device credentials"
        subtitle="Fleet defaults apply to every switch unless a switch has its own credential"
        actions={<Button variant="primary" onClick={() => setEdit({ switch_id: scope !== "default" && scope !== "all" ? scope : "" })}>Set credential</Button>}
      />
      <Card bodyClassName="p-0">
        <div className="border-b border-line p-3">
          <Select aria-label="Scope" className="w-72" value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="default">Fleet defaults</option>
            <option value="all">All credentials</option>
            {sw.data?.items.map((s) => <option key={s.id} value={s.id}>{s.hostname}</option>)}
          </Select>
        </div>
        <Loadable data={data} error={error} retry={() => mutate()}>
          {() =>
            rows.length === 0 ? (
              <Empty>{scope === "default" ? "No fleet default credentials. Add REST, SNMPv3 and (optionally) SSH defaults to start monitoring." : "No credentials for this selection."}</Empty>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Applies to</Th>
                    <Th>Protocol</Th>
                    <Th>Purpose</Th>
                    <Th>Username</Th>
                    <Th>Secret</Th>
                    <Th>Parameters</Th>
                    <Th>Updated</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id}>
                      <Td>{c.switch_id === null ? <Badge tone="accent">fleet default</Badge> : names[c.switch_id] || `#${c.switch_id}`}</Td>
                      <Td>{KIND_LABEL[c.kind]}</Td>
                      <Td>{c.purpose === "config" ? "configuration" : "monitoring"}</Td>
                      <Td className="font-mono text-xs">{c.username}</Td>
                      <Td className="font-mono text-xs text-muted">{c.secret}</Td>
                      <Td className="text-xs">{Object.entries(c.params).map(([k, v]) => `${k}=${v}`).join(", ") || "–"}</Td>
                      <Td className="text-xs">{fmtDate(c.updated_at)}</Td>
                      <Td className="whitespace-nowrap text-right">
                        <Button size="sm" variant="ghost" onClick={() => setEdit({ switch_id: c.switch_id === null ? "" : String(c.switch_id), kind: c.kind, purpose: c.purpose, username: c.username })}>Replace</Button>
                        <Button size="sm" variant="ghost" onClick={() => setDel(c)}>Delete</Button>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )
          }
        </Loadable>
      </Card>
      {edit && <CredentialEditor switches={sw.data?.items || []} preset={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); toast("ok", "Credential saved"); mutate(); }} />}
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} danger title="Delete credential" message="The stored credential is deleted. Switches that relied on it fall back to the fleet default, if any." confirmLabel="Delete" onConfirm={async () => { await api(`/credentials/${del!.id}`, { method: "DELETE" }); mutate(); }} />
    </div>
  );
}
