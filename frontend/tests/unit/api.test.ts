import { api, ApiError, buildUrl, errorMessage, onAuthError } from "@/lib/api";

describe("api client", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.cookie = "anm_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  it("builds URLs and drops empty query values", () => {
    expect(buildUrl("/switches", { q: "core", status: "", page: 2, x: null })).toBe("/api/v1/switches?q=core&page=2");
  });

  it("sends the CSRF token on state-changing requests only", async () => {
    document.cookie = "anm_csrf=tok123";
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }));
    await api("/jobs", { method: "POST", body: { a: 1 } });
    await api("/jobs");
    const post = f.mock.calls[0][1] as RequestInit;
    const get = f.mock.calls[1][1] as RequestInit;
    expect((post.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
    expect((get.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
    expect(post.credentials).toBe("same-origin");
  });

  it("raises ApiError with the backend code and message, and notifies auth listeners on 401", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "unauthorized", message: "Not signed in" } }), { status: 401, headers: { "content-type": "application/json" } }),
    );
    const seen: string[] = [];
    const off = onAuthError((e) => seen.push(e.code));
    await expect(api("/auth/me")).rejects.toMatchObject({ status: 401, code: "unauthorized", message: "Not signed in" });
    off();
    expect(seen).toEqual(["unauthorized"]);
  });

  it("lists validation errors in messages", () => {
    const e = new ApiError(422, "validation_error", "Invalid request", { errors: [{ loc: ["body", "mgmt_ip"], msg: "not an IP" }] });
    expect(errorMessage(e)).toBe("Invalid request: mgmt_ip: not an IP");
    expect(errorMessage(new Error("x"))).toBe("x");
  });
});
