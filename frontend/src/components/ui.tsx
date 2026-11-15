"use client";

import { AlertTriangle, ChevronLeft, ChevronRight, Loader2, X } from "lucide-react";
import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from "react";
import { errorMessage } from "@/lib/api";
import { relTime } from "@/lib/format";

export function cx(...c: (string | false | null | undefined)[]): string {
  return c.filter(Boolean).join(" ");
}

/* ----------------------------------------------------------------- buttons */

type BtnVariant = "primary" | "secondary" | "danger" | "ghost";
export function Button({
  variant = "secondary",
  size = "md",
  loading,
  className,
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md"; loading?: boolean }) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-accent text-accent-fg hover:brightness-110 border-transparent",
    secondary: "bg-panel-2 text-fg hover:bg-line border-line",
    danger: "bg-bad text-white hover:brightness-110 border-transparent",
    ghost: "bg-transparent text-fg hover:bg-panel-2 border-transparent",
  };
  return (
    <button
      type="button"
      {...rest}
      disabled={rest.disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-3 text-sm",
        styles[variant],
        className,
      )}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <Link
      href={href}
      className={cx(
        "inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-panel-2 px-3 text-sm font-medium hover:bg-line",
        className,
      )}
    >
      {children}
    </Link>
  );
}

/* ----------------------------------------------------------------- layout */

export function Card({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatTile({
  label,
  value,
  hint,
  tone,
  href,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: "ok" | "warn" | "bad" | "info";
  href?: string;
}) {
  const toneCls = tone ? { ok: "text-ok", warn: "text-warn", bad: "text-bad", info: "text-info" }[tone] : "";
  const body = (
    <div className="rounded-lg border border-line bg-panel p-4 transition hover:border-muted">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={cx("tabular mt-1 text-2xl font-semibold", toneCls)}>{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
  return href ? <Link href={href}>{body}</Link> : body;
}

/* ----------------------------------------------------------------- badges */

type Tone = "ok" | "warn" | "bad" | "info" | "muted" | "sim" | "accent";
export function Badge({ tone = "muted", children, title }: { tone?: Tone; children: React.ReactNode; title?: string }) {
  const cls: Record<Tone, string> = {
    ok: "bg-ok/15 text-ok border-ok/30",
    warn: "bg-warn/15 text-warn border-warn/30",
    bad: "bg-bad/15 text-bad border-bad/30",
    info: "bg-info/15 text-info border-info/30",
    muted: "bg-panel-2 text-muted border-line",
    sim: "bg-sim/15 text-sim border-sim/40",
    accent: "bg-accent/15 text-accent border-accent/40",
  };
  return (
    <span
      title={title}
      className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-xs font-medium", cls[tone])}
    >
      {children}
    </span>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "online" || status === "success" || status === "completed" || status === "verified" || status === "ok"
      ? "ok"
      : status === "offline" || status === "failed" || status === "critical" || status === "verify_failed" || status === "rejected" || status === "error"
        ? "bad"
        : status === "warning" || status === "partial" || status === "pending_approval" || status === "degraded"
          ? "warn"
          : status === "running" || status === "queued" || status === "info"
            ? "info"
            : "muted";
  return <Badge tone={tone}>{status.replace(/_/g, " ")}</Badge>;
}

export function RiskBadge({ risk }: { risk: string }) {
  const tone: Tone = risk === "critical" ? "bad" : risk === "high" ? "warn" : risk === "medium" ? "info" : "ok";
  return <Badge tone={tone}>{risk} risk</Badge>;
}

/** Shown wherever data comes from the built-in simulator so it is never mistaken for real hardware. */
export function SimBadge({ show = true }: { show?: boolean }) {
  if (!show) return null;
  return (
    <Badge tone="sim" title="This device is simulated by the built-in simulator. It is not real hardware.">
      SIMULATED
    </Badge>
  );
}

export function StaleBadge({ at, stale }: { at: string | null | undefined; stale: boolean }) {
  if (!at) return <Badge tone="muted" title="No data has been collected yet">no data</Badge>;
  if (!stale) return null;
  return (
    <Badge tone="warn" title={`Last successful collection ${relTime(at)}. Values may be out of date.`}>
      stale · {relTime(at)}
    </Badge>
  );
}

/* ----------------------------------------------------------------- feedback */

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-4 text-sm text-muted" role="status">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="flex-1">{errorMessage(error)}</div>
      {onRetry && (
        <Button size="sm" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "bad" | "sim"; children: React.ReactNode }) {
  const cls = {
    info: "border-info/40 bg-info/10",
    warn: "border-warn/40 bg-warn/10",
    bad: "border-bad/40 bg-bad/10",
    sim: "border-sim/40 bg-sim/10",
  }[tone];
  return <div className={cx("rounded-md border p-3 text-sm", cls)}>{children}</div>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="p-6 text-center text-sm text-muted">{children}</div>;
}

/** Wraps a data load: spinner first time, error with retry, otherwise children. */
export function Loadable<T>({
  data,
  error,
  retry,
  children,
}: {
  data: T | undefined;
  error: unknown;
  retry?: () => void;
  children: (d: T) => React.ReactNode;
}) {
  if (error && data === undefined) return <ErrorBox error={error} onRetry={retry} />;
  if (data === undefined) return <Spinner />;
  return (
    <>
      {error ? <ErrorBox error={error} onRetry={retry} /> : null}
      {children(data)}
    </>
  );
}

/* ----------------------------------------------------------------- forms */

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: React.ReactNode;
  error?: string;
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-muted">
        {label}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-muted">{hint}</p>}
      {error && <p className="text-xs text-bad">{error}</p>}
    </div>
  );
}

const inputCls =
  "h-9 w-full rounded-md border border-line bg-panel-2 px-2.5 text-sm placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputCls, props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputCls, "pr-7", props.className)} />;
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className={cx(
        "w-full rounded-md border border-line bg-panel-2 p-2.5 text-sm placeholder:text-muted focus:border-accent focus:outline-none",
        props.className,
      )}
    />
  );
}

export function Checkbox({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input
        id={id}
        type="checkbox"
        className="h-4 w-4 accent-[var(--c-accent)]"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

/* ----------------------------------------------------------------- tables */

export function Table({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  );
}
export function Th({ children, className }: { children?: React.ReactNode; className?: string }) {
  return (
    <th className={cx("whitespace-nowrap border-b border-line px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted", className)}>
      {children}
    </th>
  );
}
export function Td({ children, className, colSpan }: { children?: React.ReactNode; className?: string; colSpan?: number }) {
  return (
    <td colSpan={colSpan} className={cx("border-b border-line/60 px-3 py-2 align-middle", className)}>
      {children}
    </td>
  );
}

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="flex items-center justify-between gap-2 px-1 py-2 text-xs text-muted">
      <span className="tabular">
        {total === 0 ? "No results" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}
      </span>
      <div className="flex items-center gap-1">
        <Button size="sm" variant="ghost" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="tabular">
          {page} / {pages}
        </span>
        <Button size="sm" variant="ghost" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- tabs */

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { id: T; label: string; hidden?: boolean }[];
  value: T;
  onChange: (t: T) => void;
}) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {tabs
        .filter((t) => !t.hidden)
        .map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={value === t.id}
            onClick={() => onChange(t.id)}
            className={cx(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
              value === t.id ? "border-accent font-medium text-fg" : "border-transparent text-muted hover:text-fg",
            )}
          >
            {t.label}
          </button>
        ))}
    </div>
  );
}

/* ----------------------------------------------------------------- modal */

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  open: boolean;
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh]">
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        className={cx("w-full rounded-lg border border-line bg-panel shadow-2xl focus:outline-none", wide ? "max-w-4xl" : "max-w-lg")}
      >
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="font-semibold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:bg-panel-2 hover:text-fg">
            <X className="h-4 w-4" />
          </button>
        </header>
        <div className="max-h-[70vh] overflow-y-auto p-4">{children}</div>
        {footer && <footer className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

/**
 * Confirmation dialog. When `typeToConfirm` is set the user must type that exact text before confirming,
 * which is used for destructive actions such as deleting a switch or a user.
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  danger,
  typeToConfirm,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  typeToConfirm?: string;
  onConfirm: () => Promise<unknown> | unknown;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (open) {
      setTyped("");
      setErr(null);
    }
  }, [open]);
  const ok = !typeToConfirm || typed === typeToConfirm;
  return (
    <Modal
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant={danger ? "danger" : "primary"}
            disabled={!ok}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              setErr(null);
              try {
                await onConfirm();
                onClose();
              } catch (e) {
                setErr(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <div>{message}</div>
        {typeToConfirm && (
          <Field label={`Type "${typeToConfirm}" to confirm`}>
            <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" aria-label="Confirmation text" />
          </Field>
        )}
        <ErrorBox error={err} />
      </div>
    </Modal>
  );
}

/* ----------------------------------------------------------------- toasts */

interface Toast {
  id: number;
  tone: "ok" | "bad" | "info";
  text: string;
}
const ToastCtx = createContext<(tone: Toast["tone"], text: string) => void>(() => undefined);

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((tone: Toast["tone"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 6000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto rounded-md border bg-panel p-3 text-sm shadow-lg",
              t.tone === "ok" ? "border-ok/50" : t.tone === "bad" ? "border-bad/50" : "border-info/50",
            )}
          >
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}

/* ----------------------------------------------------------------- misc */

export function KV({ items }: { items: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {items.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 border-b border-line/50 pb-1.5">
          <dt className="text-muted">{k}</dt>
          <dd className="text-right break-all">{v ?? "–"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Meter({ value, max = 100, tone }: { value: number | null | undefined; max?: number; tone?: "auto" }) {
  const pct = value === null || value === undefined || !max ? 0 : Math.min(100, (value / max) * 100);
  const color = tone === "auto" || tone === undefined ? (pct >= 90 ? "bg-bad" : pct >= 75 ? "bg-warn" : "bg-ok") : "bg-accent";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-panel-2" role="meter" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cx("h-full", color)} style={{ width: `${pct}%` }} />
    </div>
  );
}
