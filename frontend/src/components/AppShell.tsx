"use client";

import { Bell, LogOut, Menu, Moon, Search, Sun, User as UserIcon, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, onAuthError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useApi } from "@/lib/hooks";
import { NAV } from "@/lib/nav";
import type { Page } from "@/lib/types";
import { Credit, Logo } from "./Credit";
import { Badge, cx, Spinner, StatusBadge } from "./ui";

const ROLE_LABEL: Record<string, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  monitor: "Monitor",
  viewer: "Viewer",
};
export const roleLabel = (r: string) => ROLE_LABEL[r] || r;

interface SearchResult {
  switches: { id: number; hostname: string; mgmt_ip: string; status: string }[];
  ports: { switch_id: number; hostname: string; port: string; description: string }[];
  devices: { mac: string; switch_id: number; hostname: string; port: string; vlan_id: number | null }[];
}

function GlobalSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [open, setOpen] = useState(false);
  const router = useRouter();
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (q.trim().length < 2) {
      setRes(null);
      return;
    }
    const t = setTimeout(() => {
      api<SearchResult>("/search", { query: { q: q.trim() } })
        .then((r) => {
          setRes(r);
          setOpen(true);
        })
        .catch(() => setRes(null));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const go = (href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  };
  const empty = res && !res.switches.length && !res.ports.length && !res.devices.length;

  return (
    <div ref={box} className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-muted" aria-hidden />
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => res && setOpen(true)}
        placeholder="Search switches, IPs, ports, MAC addresses…"
        aria-label="Global search"
        className="h-9 w-full rounded-md border border-line bg-panel-2 pl-8 pr-3 text-sm placeholder:text-muted focus:border-accent focus:outline-none"
      />
      {open && res && (
        <div className="absolute left-0 right-0 top-10 z-40 max-h-96 overflow-y-auto rounded-md border border-line bg-panel shadow-xl">
          {empty && <div className="p-3 text-sm text-muted">No matches</div>}
          {res.switches.length > 0 && <div className="px-3 pt-2 text-xs uppercase text-muted">Switches</div>}
          {res.switches.map((s) => (
            <button key={`s${s.id}`} type="button" onClick={() => go(`/switches/${s.id}`)} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-panel-2">
              <span>
                {s.hostname} <span className="text-muted">{s.mgmt_ip}</span>
              </span>
              <StatusBadge status={s.status} />
            </button>
          ))}
          {res.ports.length > 0 && <div className="px-3 pt-2 text-xs uppercase text-muted">Ports</div>}
          {res.ports.map((p) => (
            <button key={`p${p.switch_id}-${p.port}`} type="button" onClick={() => go(`/switches/${p.switch_id}?tab=ports&port=${encodeURIComponent(p.port)}`)} className="block w-full px-3 py-1.5 text-left text-sm hover:bg-panel-2">
              {p.hostname} port {p.port} <span className="text-muted">{p.description}</span>
            </button>
          ))}
          {res.devices.length > 0 && <div className="px-3 pt-2 text-xs uppercase text-muted">Devices</div>}
          {res.devices.map((d) => (
            <button key={`d${d.mac}-${d.switch_id}`} type="button" onClick={() => go(`/devices?q=${encodeURIComponent(d.mac)}`)} className="block w-full px-3 py-1.5 text-left text-sm hover:bg-panel-2">
              <span className="font-mono">{d.mac}</span> <span className="text-muted">on {d.hostname} port {d.port}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function AlertBell() {
  const { can } = useAuth();
  const { data } = useApi<Page<unknown>>(can("alert.view") ? "/alerts" : null, { status: "active", page_size: 1 }, { live: true });
  if (!can("alert.view")) return null;
  const n = data?.total ?? 0;
  return (
    <Link href="/alerts" className="relative rounded-md p-2 hover:bg-panel-2" aria-label={`${n} active alerts`}>
      <Bell className="h-5 w-5" />
      {n > 0 && (
        <span className="tabular absolute -right-0.5 -top-0.5 rounded-full bg-bad px-1.5 text-[10px] font-semibold text-white">
          {n > 99 ? "99+" : n}
        </span>
      )}
    </Link>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, loading, error, canAny, theme, setTheme, mode, setMode, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);

  useEffect(
    () =>
      onAuthError((e) => {
        if (e.code === "password_change_required") router.replace("/change-password");
        else if (e.status === 401) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
      }),
    [router],
  );

  useEffect(() => {
    if (error?.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    if (error?.code === "password_change_required" || me?.must_change_password) router.replace("/change-password");
  }, [error, me, router, pathname]);

  useEffect(() => setNavOpen(false), [pathname]);

  if (loading || !me) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        {error && error.status !== 401 ? <p className="text-sm text-bad">{error.message}</p> : <Spinner label="Loading session" />}
      </div>
    );
  }

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname === href || (pathname.startsWith(href + "/") && href !== "/changes") || (href === "/changes" && pathname.startsWith("/changes/") && pathname !== "/changes/new"));

  const nav = (
    <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3" aria-label="Main">
      {NAV.map((sec) => {
        const items = sec.items.filter((i) => canAny(...i.anyOf) && !(i.pro && mode === "simple"));
        if (!items.length) return null;
        return (
          <div key={sec.section}>
            <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{sec.section}</div>
            {items.map((i) => (
              <Link
                key={i.href}
                href={i.href}
                className={cx(
                  "flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm",
                  isActive(i.href) ? "bg-accent/15 font-medium text-accent" : "text-fg/85 hover:bg-panel-2",
                )}
              >
                <i.icon className="h-4 w-4 shrink-0" aria-hidden />
                {i.label}
              </Link>
            ))}
          </div>
        );
      })}
    </nav>
  );

  const mfaGate = me.mfa_setup_required && pathname !== "/profile";

  return (
    <div className="flex min-h-screen">
      <aside className={cx("fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-line bg-panel transition-transform lg:translate-x-0", navOpen ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex h-14 items-center justify-between border-b border-line px-4">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <Logo size={24} />
            Network Manager
          </Link>
          <button type="button" className="lg:hidden" onClick={() => setNavOpen(false)} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>
        {nav}
        <div className="border-t border-line p-3 text-xs text-muted">Internal use only · Aruba AOS-Switch</div>
      </aside>
      {navOpen && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setNavOpen(false)} aria-hidden />}

      <div className="flex min-w-0 flex-1 flex-col lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-line bg-panel/95 px-4 backdrop-blur">
          <button type="button" className="lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-1">
            <div className="hidden items-center rounded-md border border-line p-0.5 text-xs sm:flex" role="group" aria-label="Interface mode">
              {(["simple", "pro"] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  aria-pressed={mode === m}
                  onClick={() => setMode(m)}
                  className={cx("rounded px-2 py-1 capitalize", mode === m ? "bg-accent text-accent-fg" : "text-muted hover:text-fg")}
                >
                  {m}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              className="rounded-md p-2 hover:bg-panel-2"
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </button>
            <AlertBell />
            <Link href="/profile" className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-panel-2" aria-label="My profile">
              <UserIcon className="h-5 w-5" />
              <span className="hidden text-sm md:inline">
                {me.username} <span className="text-muted">· {roleLabel(me.role)}</span>
              </span>
            </Link>
            <button type="button" onClick={logout} className="rounded-md p-2 hover:bg-panel-2" aria-label="Sign out">
              <LogOut className="h-5 w-5" />
            </button>
          </div>
        </header>
        {me.simulator_enabled && (
          <div className="border-b border-sim/40 bg-sim/10 px-4 py-1.5 text-xs text-sim">
            Simulator mode is enabled on this server. Devices marked <Badge tone="sim">SIMULATED</Badge> are generated by the built-in simulator and are not real hardware.
          </div>
        )}
        <main className="min-w-0 flex-1 p-4 lg:p-6">
          {mfaGate ? (
            <div className="mx-auto max-w-lg rounded-lg border border-warn/50 bg-warn/10 p-6 text-sm">
              <h1 className="mb-2 text-lg font-semibold">Two-factor authentication required</h1>
              <p className="mb-4">Your role requires two-factor authentication. Set it up on your profile before continuing.</p>
              <Link href="/profile" className="inline-flex h-9 items-center rounded-md bg-accent px-3 font-medium text-accent-fg">
                Set up two-factor authentication
              </Link>
            </div>
          ) : (
            children
          )}
        </main>
        <Credit className="border-t border-line px-4 py-3" />
      </div>
    </div>
  );
}
