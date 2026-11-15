"use client";

import { Zap } from "lucide-react";
import { fmtBps } from "@/lib/format";
import type { Port } from "@/lib/types";
import { cx } from "./ui";

export type PortState = "up" | "down" | "disabled" | "errors" | "fault";

export function portState(p: Port): PortState {
  if (p.poe?.fault) return "fault";
  if (!p.admin_up) return "disabled";
  if (!p.oper_up) return "down";
  if (p.in_errors + p.out_errors > 0) return "errors";
  return "up";
}

const STATE_CLS: Record<PortState, string> = {
  up: "bg-ok/25 border-ok text-fg",
  down: "bg-panel-2 border-line text-muted",
  disabled: "bg-bad/10 border-bad/60 border-dashed text-muted",
  errors: "bg-warn/25 border-warn text-fg",
  fault: "bg-bad/30 border-bad text-fg",
};

const STATE_LABEL: Record<PortState, string> = {
  up: "Up",
  down: "Down",
  disabled: "Administratively disabled",
  errors: "Up with errors",
  fault: "PoE fault",
};

function PortBox({ p, selected, onClick }: { p: Port; selected: boolean; onClick?: () => void }) {
  const st = portState(p);
  const delivering = p.poe && (p.poe.power_drawn_w || 0) > 0;
  const title = [
    `Port ${p.name}${p.description ? ` – ${p.description}` : ""}`,
    STATE_LABEL[st],
    p.oper_up && p.speed_mbps ? `${p.speed_mbps >= 1000 ? p.speed_mbps / 1000 + " Gbps" : p.speed_mbps + " Mbps"} ${p.duplex || ""}` : "",
    `VLAN ${p.untagged_vlan ?? "–"}${p.tagged_vlans.length ? ` (+tagged ${p.tagged_vlans.join(",")})` : ""}`,
    p.oper_up ? `in ${fmtBps(p.in_bps)} / out ${fmtBps(p.out_bps)}` : "",
    p.poe ? `PoE ${p.poe.detection_status}${delivering ? ` ${p.poe.power_drawn_w} W` : ""}` : "",
    p.is_uplink ? "Uplink" : "",
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <button
      type="button"
      title={title}
      aria-label={`Port ${p.name}, ${STATE_LABEL[st]}`}
      aria-pressed={selected}
      onClick={onClick}
      className={cx(
        "relative flex h-11 w-11 flex-col items-center justify-center rounded border-2 text-xs font-semibold transition",
        STATE_CLS[st],
        selected && "ring-2 ring-accent ring-offset-2 ring-offset-[var(--c-panel)]",
        onClick ? "cursor-pointer hover:brightness-125" : "cursor-default",
      )}
    >
      <span>{p.name}</span>
      {delivering && <Zap className="absolute right-0.5 top-0.5 h-3 w-3 text-warn" aria-hidden />}
      {p.is_uplink && <span className="absolute bottom-0.5 h-0.5 w-5 rounded bg-info" aria-hidden />}
    </button>
  );
}

const SLOT_PORT = /^([A-L])(\d{1,2})$/;

/** Splits ports into module slots for a 5400R zl2 chassis (A1..L24); fixed-port switches have no slots. */
export function groupBySlot(ports: Port[]): { slot: string | null; ports: Port[] }[] {
  const slots = new Map<string, Port[]>();
  const fixed: Port[] = [];
  for (const p of ports) {
    const m = SLOT_PORT.exec(p.name);
    if (m) {
      if (!slots.has(m[1])) slots.set(m[1], []);
      slots.get(m[1])!.push(p);
    } else {
      fixed.push(p);
    }
  }
  const num = (p: Port) => Number(SLOT_PORT.exec(p.name)?.[2] ?? 0);
  const out: { slot: string | null; ports: Port[] }[] = [...slots.keys()]
    .sort()
    .map((slot) => ({ slot, ports: slots.get(slot)!.sort((a, b) => num(a) - num(b)) }));
  if (fixed.length) out.unshift({ slot: null, ports: fixed.sort((a, b) => a.if_index - b.if_index) });
  return out;
}

/**
 * Front-panel view. Fixed-port switches (2540, 2930F): odd ports on the top row, even ports below, SFP/SFP+ uplinks
 * to the right. Modular chassis (5400R zl2): one block per module slot, labelled with its letter.
 * Click ports to select them for a change.
 */
export function PortPanel({
  ports,
  selected,
  onToggle,
}: {
  ports: Port[];
  selected?: Set<string>;
  onToggle?: (name: string) => void;
}) {
  const box = (p: Port) => <PortBox key={p.id} p={p} selected={!!selected?.has(p.name)} onClick={onToggle ? () => onToggle(p.name) : undefined} />;
  const rows = (list: Port[]) => (
    <>
      <div className="flex gap-1.5">{list.filter((_, i) => i % 2 === 0).map(box)}</div>
      <div className="flex gap-1.5">{list.filter((_, i) => i % 2 === 1).map(box)}</div>
    </>
  );
  const groups = groupBySlot(ports);
  return (
    <div>
      <div className="overflow-x-auto">
        <div className="inline-flex flex-col gap-3">
          {groups.map(({ slot, ports: list }) => {
            const copper = list.filter((p) => !/SFP/i.test(p.port_type));
            const sfp = list.filter((p) => /SFP/i.test(p.port_type));
            return (
              <div key={slot ?? "fixed"} className="inline-flex gap-6 rounded-lg border border-line bg-panel-2 p-3">
                {slot && (
                  <div className="flex w-14 flex-col justify-center text-xs text-muted">
                    <span>Slot</span>
                    <span className="text-lg font-semibold text-fg">{slot}</span>
                  </div>
                )}
                {copper.length > 0 && <div className="flex flex-col gap-1.5">{rows(copper)}</div>}
                {sfp.length > 0 && (
                  <div className={cx("flex flex-col gap-1.5", copper.length > 0 && "border-l border-line pl-6")}>{rows(sfp)}</div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted">
        {(Object.keys(STATE_LABEL) as PortState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1">
            <span className={cx("inline-block h-3 w-3 rounded-sm border-2", STATE_CLS[s])} /> {STATE_LABEL[s]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1">
          <Zap className="h-3 w-3 text-warn" /> Delivering PoE
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-0.5 w-3 bg-info" /> Uplink
        </span>
      </div>
    </div>
  );
}
