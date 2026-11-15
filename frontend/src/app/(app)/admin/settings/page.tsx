"use client";

import { useState } from "react";
import { Badge, Button, Card, Checkbox, Input, Loadable, PageHeader, Select, StatusBadge, Table, Tabs, Td, Th, useToast } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { PollingJob, Setting } from "@/lib/types";

const CHOICES: Record<string, string[]> = {
  "changes.require_approval_risk": ["medium", "high", "critical"],
};

function SettingRow({ s, onSaved }: { s: Setting; onSaved: () => void }) {
  const toast = useToast();
  const [value, setValue] = useState<unknown>(s.value);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(value) !== JSON.stringify(s.value);
  const save = async () => {
    setBusy(true);
    try {
      await api(`/settings/${encodeURIComponent(s.key)}`, { method: "PUT", body: { value } });
      toast("ok", `${s.description} saved`);
      onSaved();
    } catch (e) {
      toast("bad", errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  let control: React.ReactNode;
  if (CHOICES[s.key]) {
    control = (
      <Select aria-label={s.description} className="w-40" value={String(value)} disabled={!s.editable} onChange={(e) => setValue(e.target.value)}>
        {CHOICES[s.key].map((c) => <option key={c} value={c}>{c}</option>)}
      </Select>
    );
  } else if (typeof s.default === "boolean") {
    control = <Checkbox label={value ? "On" : "Off"} checked={Boolean(value)} disabled={!s.editable} onChange={setValue} />;
  } else if (typeof s.default === "number") {
    control = <Input aria-label={s.description} className="w-32" type="number" value={String(value ?? "")} disabled={!s.editable} onChange={(e) => setValue(e.target.value === "" ? "" : Number(e.target.value))} />;
  } else {
    control = <Input aria-label={s.description} className="w-64" value={String(value ?? "")} disabled={!s.editable} onChange={(e) => setValue(e.target.value)} />;
  }
  return (
    <tr>
      <Td>
        {s.description}
        <div className="font-mono text-xs text-muted">{s.key}</div>
      </Td>
      <Td>{control}</Td>
      <Td className="text-xs text-muted">default {String(s.default)}</Td>
      <Td className="whitespace-nowrap text-right">
        {s.editable && dirty && (
          <>
            <Button size="sm" variant="ghost" onClick={() => setValue(s.value)}>Undo</Button>
            <Button size="sm" variant="primary" loading={busy} onClick={save}>Save</Button>
          </>
        )}
        {!s.editable && <Badge>read only</Badge>}
      </Td>
    </tr>
  );
}

function SettingsTab({ category }: { category: string }) {
  const { data, error, mutate } = useApi<Setting[]>("/settings");
  return (
    <Card bodyClassName="p-0">
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) => (
          <Table>
            <thead>
              <tr>
                <Th>Setting</Th>
                <Th>Value</Th>
                <Th />
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.filter((s) => s.category === category).map((s) => (
                <SettingRow key={`${s.key}-${JSON.stringify(s.value)}`} s={s} onSaved={() => mutate()} />
              ))}
            </tbody>
          </Table>
        )}
      </Loadable>
    </Card>
  );
}

function PollingTab() {
  const { can } = useAuth();
  const toast = useToast();
  const { data, error, mutate } = useApi<PollingJob[]>("/polling", undefined, { live: true });
  const toggle = async (p: PollingJob) => {
    try {
      await api(`/polling/${p.category}`, { method: "PATCH", body: { enabled: !p.enabled } });
      mutate();
    } catch (e) {
      toast("bad", errorMessage(e));
    }
  };
  return (
    <Card bodyClassName="p-0">
      <p className="px-4 pt-3 text-xs text-muted">Intervals are set on the Operational tab. Each run polls every monitored switch in parallel.</p>
      <Loadable data={data} error={error} retry={() => mutate()}>
        {(rows) => (
          <Table>
            <thead>
              <tr>
                <Th>Category</Th>
                <Th>Interval</Th>
                <Th>Enabled</Th>
                <Th>Last run</Th>
                <Th>Duration</Th>
                <Th>Result</Th>
                <Th>Switches</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.category}>
                  <Td className="font-medium">{p.category}</Td>
                  <Td className="tabular">{p.interval_seconds}s</Td>
                  <Td>{p.enabled ? <Badge tone="ok">on</Badge> : <Badge>paused</Badge>}</Td>
                  <Td className="text-xs">{relTime(p.last_run_at)}</Td>
                  <Td className="tabular text-xs">{p.last_duration_ms === null ? "–" : `${p.last_duration_ms} ms`}</Td>
                  <Td>
                    <StatusBadge status={p.last_status} />
                    {p.last_error && <div className="max-w-64 truncate text-xs text-bad" title={p.last_error}>{p.last_error}</div>}
                  </Td>
                  <Td className="tabular text-xs">{p.switches_polled}{p.switches_failed > 0 && <span className="text-bad"> · {p.switches_failed} failed</span>}</Td>
                  <Td className="text-right">{can("settings.operational") && <Button size="sm" variant="ghost" onClick={() => toggle(p)}>{p.enabled ? "Pause" : "Resume"}</Button>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Loadable>
    </Card>
  );
}

type Tab = "operational" | "security" | "polling";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("operational");
  return (
    <div>
      <PageHeader title="Settings & polling" subtitle="Changes take effect immediately and are recorded in the audit log" />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { id: "operational", label: "Operational" },
          { id: "security", label: "Security" },
          { id: "polling", label: "Polling status" },
        ]}
      />
      {tab === "polling" ? <PollingTab /> : <SettingsTab category={tab} />}
    </div>
  );
}
