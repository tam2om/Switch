// Thin fetch wrapper for the backend REST API.
// Session auth uses an HttpOnly cookie; state-changing requests send the CSRF token from the anm_csrf cookie.

export const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;
  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function readCookie(name: string): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.split("; ").find((c) => c.startsWith(name + "="));
  return m ? decodeURIComponent(m.slice(name.length + 1)) : "";
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  const url = path.startsWith("/api/") ? path : API_BASE + path;
  if (!query) return url;
  const qs = Object.entries(query)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
}

type Listener = (e: ApiError) => void;
const authListeners = new Set<Listener>();
/** Subscribe to authentication failures (401 / password change required) so the shell can redirect. */
export function onAuthError(fn: Listener): () => void {
  authListeners.add(fn);
  return () => authListeners.delete(fn);
}

export async function api<T = unknown>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query; raw?: boolean } = {},
): Promise<T> {
  const method = (opts.method || "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = readCookie("anm_csrf");
  const res = await fetch(buildUrl(path, opts.query), {
    method,
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    let details: Record<string, unknown> = {};
    try {
      const data = await res.json();
      const d = data?.detail;
      if (d && typeof d === "object") {
        code = d.code || code;
        message = d.message || message;
        details = d.details || {};
      } else if (typeof d === "string") {
        message = d;
      }
    } catch {
      /* non-JSON error body */
    }
    const err = new ApiError(res.status, code, message, details);
    if (res.status === 401 || code === "password_change_required") authListeners.forEach((l) => l(err));
    throw err;
  }
  if (opts.raw) return (await res.text()) as T;
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? await res.json() : await res.text()) as T;
}

export const fetcher = <T,>(path: string) => api<T>(path);

/** Human readable message for any thrown value. Validation errors list the failing fields. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const errs = (e.details as { errors?: unknown })?.errors;
    if (Array.isArray(errs) && errs.length) {
      const parts = errs.map((x) => {
        if (typeof x === "string") return x;
        const o = x as { loc?: string[]; msg?: string };
        const field = (o.loc || []).filter((p) => p !== "body" && p !== "query").join(".");
        return field ? `${field}: ${o.msg}` : String(o.msg);
      });
      return `${e.message}: ${parts.join("; ")}`;
    }
    return e.message;
  }
  if (e instanceof Error) return e.message;
  return String(e);
}
