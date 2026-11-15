"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { parseList } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Group, Site, SwitchDetail } from "@/lib/types";
import { Button, Checkbox, ErrorBox, Field, Input, Select, Textarea } from "./ui";

/** Create or edit a switch's inventory record. Device credentials are managed separately. */
export function SwitchForm({
  initial,
  onSaved,
  onCancel,
}: {
  initial?: SwitchDetail;
  onSaved: (sw: SwitchDetail) => void;
  onCancel: () => void;
}) {
  const sites = useApi<Site[]>("/sites");
  const groups = useApi<Group[]>("/groups");
  const [f, setF] = useState({
    hostname: initial?.hostname || "",
    mgmt_ip: initial?.mgmt_ip || "",
    site_id: initial?.site_id ? String(initial.site_id) : "",
    location: initial?.location || "",
    building: initial?.building || "",
    floor: initial?.floor || "",
    department: initial?.department || "",
    mgmt_vlan: initial?.mgmt_vlan ? String(initial.mgmt_vlan) : "",
    uplink_ports: (initial?.uplink_ports || []).join(", "),
    monitoring_enabled: initial?.monitoring_enabled ?? true,
    ssh: initial?.protocols?.ssh ?? true,
    rest: initial?.protocols?.rest ?? true,
    snmp: initial?.protocols?.snmp ?? true,
    notes: initial?.notes || "",
    group_ids: new Set<number>((initial?.groups || []).map((g) => g.id)),
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const set = <K extends keyof typeof f>(k: K, v: (typeof f)[K]) => setF((x) => ({ ...x, [k]: v }));

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const body = {
      hostname: f.hostname.trim(),
      mgmt_ip: f.mgmt_ip.trim(),
      site_id: f.site_id ? Number(f.site_id) : null,
      location: f.location,
      building: f.building,
      floor: f.floor,
      department: f.department,
      mgmt_vlan: f.mgmt_vlan ? Number(f.mgmt_vlan) : null,
      uplink_ports: parseList(f.uplink_ports),
      monitoring_enabled: f.monitoring_enabled,
      protocols: { ssh: f.ssh, rest: f.rest, snmp: f.snmp },
      notes: f.notes,
      group_ids: [...f.group_ids],
    };
    try {
      const sw = initial
        ? await api<SwitchDetail>(`/switches/${initial.id}`, { method: "PATCH", body })
        : await api<SwitchDetail>("/switches", { method: "POST", body });
      onSaved(sw);
    } catch (e2) {
      setErr(e2);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="space-y-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Hostname *" htmlFor="sw-host">
          <Input id="sw-host" value={f.hostname} onChange={(e) => set("hostname", e.target.value)} required maxLength={128} />
        </Field>
        <Field label="Management IP *" htmlFor="sw-ip" hint="Must be on an internal network.">
          <Input id="sw-ip" value={f.mgmt_ip} onChange={(e) => set("mgmt_ip", e.target.value)} required placeholder="10.0.0.10" />
        </Field>
        <Field label="Site" htmlFor="sw-site">
          <Select id="sw-site" value={f.site_id} onChange={(e) => set("site_id", e.target.value)}>
            <option value="">— none —</option>
            {sites.data?.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </Select>
        </Field>
        <Field label="Location" htmlFor="sw-loc">
          <Input id="sw-loc" value={f.location} onChange={(e) => set("location", e.target.value)} />
        </Field>
        <Field label="Building" htmlFor="sw-b">
          <Input id="sw-b" value={f.building} onChange={(e) => set("building", e.target.value)} />
        </Field>
        <Field label="Floor" htmlFor="sw-f">
          <Input id="sw-f" value={f.floor} onChange={(e) => set("floor", e.target.value)} />
        </Field>
        <Field label="Department" htmlFor="sw-d">
          <Input id="sw-d" value={f.department} onChange={(e) => set("department", e.target.value)} />
        </Field>
        <Field label="Management VLAN" htmlFor="sw-mv" hint="Changes touching this VLAN are flagged as high risk.">
          <Input id="sw-mv" type="number" min={1} max={4094} value={f.mgmt_vlan} onChange={(e) => set("mgmt_vlan", e.target.value)} />
        </Field>
        <Field label="Uplink ports" htmlFor="sw-up" hint="Comma separated, e.g. 25, 26. Changes on uplinks are high risk.">
          <Input id="sw-up" value={f.uplink_ports} onChange={(e) => set("uplink_ports", e.target.value)} />
        </Field>
        <div className="space-y-2 pt-5">
          <Checkbox label="Monitoring enabled" checked={f.monitoring_enabled} onChange={(v) => set("monitoring_enabled", v)} />
          <div className="flex flex-wrap gap-4">
            <Checkbox label="REST" checked={f.rest} onChange={(v) => set("rest", v)} />
            <Checkbox label="SNMPv3" checked={f.snmp} onChange={(v) => set("snmp", v)} />
            <Checkbox label="SSH" checked={f.ssh} onChange={(v) => set("ssh", v)} />
          </div>
        </div>
      </div>
      {groups.data && groups.data.length > 0 && (
        <Field label="Groups">
          <div className="flex flex-wrap gap-4">
            {groups.data.map((g) => (
              <Checkbox
                key={g.id}
                label={g.name}
                checked={f.group_ids.has(g.id)}
                onChange={(v) => {
                  const n = new Set(f.group_ids);
                  if (v) n.add(g.id);
                  else n.delete(g.id);
                  set("group_ids", n);
                }}
              />
            ))}
          </div>
        </Field>
      )}
      <Field label="Notes" htmlFor="sw-notes">
        <Textarea id="sw-notes" rows={2} value={f.notes} onChange={(e) => set("notes", e.target.value)} />
      </Field>
      <ErrorBox error={err} />
      <div className="flex justify-end gap-2">
        <Button onClick={onCancel}>Cancel</Button>
        <Button type="submit" variant="primary" loading={busy}>
          {initial ? "Save" : "Add switch"}
        </Button>
      </div>
    </form>
  );
}
