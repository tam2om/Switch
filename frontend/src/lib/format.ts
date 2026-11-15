export function fmtBps(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const units = ["bps", "Kbps", "Mbps", "Gbps", "Tbps"];
  let i = 0;
  let n = v;
  while (Math.abs(n) >= 1000 && i < units.length - 1) {
    n /= 1000;
    i++;
  }
  return `${n.toFixed(n >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtBytes(v: number | null | undefined): string {
  if (v === null || v === undefined) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let n = v;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return v.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${fmtNum(v, 1)}%`;
}

export function fmtWatts(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${fmtNum(v, 1)} W`;
}

export function fmtDate(v: string | null | undefined): string {
  if (!v) return "–";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return v;
  return d.toLocaleString("en-GB", {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

export function relTime(v: string | null | undefined, now: number = Date.now()): string {
  if (!v) return "never";
  const t = new Date(v).getTime();
  if (Number.isNaN(t)) return v;
  const s = Math.round((now - t) / 1000);
  if (s < 0) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function fmtUptime(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "–";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

export function titleCase(s: string): string {
  return s.replace(/[_.]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Parse "1,2, 5-8" into ["1","2","5","6","7","8"]. Port names like "A1" or "1/1" are passed through. */
export function parseList(input: string): string[] {
  const out: string[] = [];
  for (const raw of input.split(/[\s,]+/)) {
    const part = raw.trim();
    if (!part) continue;
    const m = part.match(/^(\d+)-(\d+)$/);
    if (m) {
      const a = Number(m[1]);
      const b = Number(m[2]);
      if (b >= a && b - a <= 512) for (let i = a; i <= b; i++) out.push(String(i));
      else out.push(part);
    } else out.push(part);
  }
  return Array.from(new Set(out));
}

export const PASSWORD_HINT =
  "At least 12 characters with three of: lowercase, uppercase, digits, symbols. Must not contain your username.";
