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

/**
 * Front-panel view of an Aruba 2540: odd ports on the top row, even ports below, SFP+ uplinks to the right.
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
  const copper = ports.filter((p) => !/SFP/i.test(p.port_type)).sort((a, b) => a.if_index - b.if_index);
  const sfp = ports.filter((p) => /SFP/i.test(p.port_type)).sort((a, b) => a.if_index - b.if_index);
  const top = copper.filter((_, i) => i % 2 === 0);
  const bottom = copper.filter((_, i) => i % 2 === 1);
  const sfpTop = sfp.filter((_, i) => i % 2 === 0);
  const sfpBottom = sfp.filter((_, i) => i % 2 === 1);
  const box = (p: Port) => <PortBox key={p.id} p={p} selected={!!selected?.has(p.name)} onClick={onToggle ? () => onToggle(p.name) : undefined} />;
  return (
    <div>
      <div className="overflow-x-auto">
        <div className="inline-flex gap-6 rounded-lg border border-line bg-panel-2 p-3">
          <div className="flex flex-col gap-1.5">
            <div className="flex gap-1.5">{top.map(box)}</div>
            <div className="flex gap-1.5">{bottom.map(box)}</div>
          </div>
          {sfp.length > 0 && (
            <div className="flex flex-col gap-1.5 border-l border-line pl-6">
              <div className="flex gap-1.5">{sfpTop.map(box)}</div>
              <div className="flex gap-1.5">{sfpBottom.map(box)}</div>
            </div>
          )}
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
