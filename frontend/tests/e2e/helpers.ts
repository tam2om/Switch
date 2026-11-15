import { expect, type APIRequestContext, type Page, request } from "@playwright/test";

// The end-to-end suite runs against a live development stack with the simulator enabled.
// Provide the Super Admin created with `python -m app.cli create-superadmin` through environment variables;
// no credentials are stored in the repository.
export const SUPER_USER = process.env.E2E_SUPERADMIN_USER || "superadmin";
export const SUPER_PASSWORD = process.env.E2E_SUPERADMIN_PASSWORD || "";
export const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:3000";
export const TEST_PASSWORD = "E2e-Test-Passw0rd-42!";

export function requireCredentials() {
  if (!SUPER_PASSWORD) throw new Error("Set E2E_SUPERADMIN_PASSWORD (and optionally E2E_SUPERADMIN_USER) to run the e2e suite");
}

export async function login(page: Page, username = SUPER_USER, password = SUPER_PASSWORD) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** API client authenticated as the given user (CSRF header included). */
export async function apiAs(username = SUPER_USER, password = SUPER_PASSWORD): Promise<APIRequestContext & { csrf: string }> {
  const ctx = await request.newContext({ baseURL: BASE });
  const r = await ctx.post("/api/v1/auth/login", { data: { username, password } });
  expect(r.ok(), await r.text()).toBeTruthy();
  const { csrf_token } = await r.json();
  const wrapped = await request.newContext({ baseURL: BASE, storageState: await ctx.storageState(), extraHTTPHeaders: { "X-CSRF-Token": csrf_token } });
  await ctx.dispose();
  return Object.assign(wrapped, { csrf: csrf_token });
}

export function unique(prefix: string) {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
}

export async function createUser(api: APIRequestContext, role: string) {
  const username = unique(`e2e-${role.replace("_", "")}-`);
  const r = await api.post("/api/v1/users", { data: { username, full_name: `E2E ${role}`, role, password: TEST_PASSWORD, must_change_password: false } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return { username, id: (await r.json()).id as number };
}

export async function firstSimulatedSwitch(api: APIRequestContext, index = 0) {
  const r = await api.get("/api/v1/switches", { params: { simulated: "true", status: "online", page_size: 50 } });
  const items = (await r.json()).items as { id: number; hostname: string }[];
  if (!items.length) throw new Error("No online simulated switch. Seed the simulator first (python -m app.cli seed-simulator 10).");
  return items[Math.min(index, items.length - 1)];
}
