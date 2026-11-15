import { expect, test } from "@playwright/test";
import { apiAs, createUser, firstSimulatedSwitch, login, requireCredentials, TEST_PASSWORD, unique } from "./helpers";

test.beforeAll(() => requireCredentials());

test("rejects a wrong password without revealing which field was wrong", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(unique("nobody-"));
  await page.getByLabel("Password").fill("Wrong-Password-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: /invalid username or password/i })).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test("unauthenticated visitors are sent to the login page", async ({ page }) => {
  await page.goto("/switches");
  await expect(page).toHaveURL(/\/login\?next=%2Fswitches/);
});

test("dashboard shows live fleet status and labels simulated data", async ({ page }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Switches online")).toBeVisible();
  await expect(page.getByText(/Simulator mode is enabled/)).toBeVisible();
  await expect(page.getByText("SIMULATED").first()).toBeVisible();
});

test("theme and Simple/Pro mode switches change the interface", async ({ page }) => {
  await login(page);
  await page.goto("/switches");
  await expect(page.getByRole("columnheader", { name: "Model" })).toHaveCount(0);
  await page.getByRole("button", { name: "pro" }).click();
  await expect(page.getByRole("columnheader", { name: "Model" })).toBeVisible();
  await page.getByRole("button", { name: "simple" }).click();
  const html = page.locator("html");
  const wasLight = await html.evaluate((el) => el.classList.contains("light"));
  await page.getByRole("button", { name: /Switch to (light|dark) theme/ }).click();
  await expect(html).toHaveClass(wasLight ? /dark/ : /light/);
  await page.getByRole("button", { name: /Switch to (light|dark) theme/ }).click();
});

test("global search finds a switch and opens it", async ({ page }) => {
  const api = await apiAs();
  const sw = await firstSimulatedSwitch(api);
  await login(page);
  await page.getByLabel("Global search").fill(sw.hostname);
  await page.getByRole("button", { name: new RegExp(sw.hostname) }).first().click();
  await expect(page).toHaveURL(new RegExp(`/switches/${sw.id}`));
  await expect(page.getByRole("heading", { name: new RegExp(sw.hostname) })).toBeVisible();
  await api.dispose();
});

test("port description change runs end-to-end with backup, verification and audit", async ({ page }) => {
  const api = await apiAs();
  const sw = await firstSimulatedSwitch(api, 2);
  const desc = unique("E2E-");
  await login(page);
  await page.goto(`/switches/${sw.id}?tab=ports`);
  await page.getByRole("button", { name: /^Port 3,/ }).click();
  await page.getByRole("button", { name: "Description…" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Description").fill(desc);
  await dialog.getByRole("button", { name: "Review impact" }).click();
  await expect(dialog.getByText("A verified configuration backup is taken")).toBeVisible();
  await dialog.getByRole("button", { name: "Apply change" }).click();
  await dialog.getByRole("link", { name: /Open change #\d+/ }).click();
  await expect(page.getByText("completed").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Applied and verified")).toBeVisible();
  const ports = await (await api.get(`/api/v1/switches/${sw.id}/ports`)).json();
  expect(ports.find((p: { name: string }) => p.name === "3").description).toBe(desc);
  const audit = await (await api.get("/api/v1/audit", { params: { action: "job.", page_size: 20 } })).json();
  expect(audit.items.length).toBeGreaterThan(0);
  await api.dispose();
});

test("critical change by an Admin waits for Super Admin approval and can be rejected", async ({ page, browser }) => {
  const api = await apiAs();
  const admin = await createUser(api, "admin");
  const sw = await firstSimulatedSwitch(api, 3);
  await login(page, admin.username, TEST_PASSWORD);
  await page.goto(`/switches/${sw.id}?tab=ports`);
  await page.getByRole("button", { name: /^Port 25,/ }).click();
  await page.getByRole("button", { name: "Disable" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Review impact" }).click();
  // Disabling an uplink that carries the management VLAN is classified critical and needs explicit acknowledgement.
  await expect(dialog.getByText("critical risk").first()).toBeVisible();
  const submit = dialog.getByRole("button", { name: "Submit for approval" });
  await expect(submit).toBeDisabled();
  await dialog.getByLabel(/I understand this change/).check();
  await submit.click();
  await dialog.getByRole("link", { name: /Open change #\d+/ }).click();
  await expect(page.getByText("This change is waiting for approval")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  const jobUrl = page.url();

  const ctx = await browser.newContext();
  const superPage = await ctx.newPage();
  await login(superPage);
  await superPage.goto(jobUrl);
  await superPage.getByRole("button", { name: "Reject" }).click();
  await superPage.getByLabel("Comment").fill("E2E: not now");
  await superPage.getByRole("dialog").getByRole("button", { name: "Reject" }).click();
  await expect(superPage.getByText("rejected").first()).toBeVisible();
  await ctx.close();

  const ports = await (await api.get(`/api/v1/switches/${sw.id}/ports`)).json();
  expect(ports.find((p: { name: string }) => p.name === "25").admin_up).toBe(true);
  await api.delete(`/api/v1/users/${admin.id}`);
  await api.dispose();
});

test("Viewer has read-only access and cannot reach administration", async ({ page }) => {
  const api = await apiAs();
  const viewer = await createUser(api, "viewer");
  await login(page, viewer.username, TEST_PASSWORD);
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
  await page.goto("/switches");
  await expect(page.getByRole("button", { name: "Add switch" })).toHaveCount(0);
  await page.goto("/admin/users");
  await expect(page.getByRole("alert").filter({ hasText: /permission/i })).toBeVisible();
  const sw = await firstSimulatedSwitch(api);
  await page.goto(`/switches/${sw.id}?tab=ports`);
  await page.getByRole("button", { name: /^Port 1,/ }).click();
  await expect(page.getByRole("button", { name: "Disable" })).toHaveCount(0);
  await api.delete(`/api/v1/users/${viewer.id}`);
  await api.dispose();
});

test("Super Admin creates a user from the user management page", async ({ page }) => {
  const api = await apiAs();
  const username = unique("e2e-ui-");
  await login(page);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Create user" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Username").fill(username);
  await dialog.getByLabel("Full name").fill("E2E UI User");
  await dialog.getByLabel("Role").selectOption("monitor");
  await dialog.getByLabel("Initial password").fill(TEST_PASSWORD);
  await dialog.getByRole("button", { name: "Create user" }).click();
  await page.getByLabel("Search users").fill(username);
  await expect(page.getByRole("cell", { name: new RegExp(username) })).toBeVisible();
  const users = await (await api.get("/api/v1/users", { params: { q: username } })).json();
  expect(users.items[0].role).toBe("monitor");
  expect(users.items[0].must_change_password).toBe(true);
  await api.delete(`/api/v1/users/${users.items[0].id}`);
  await api.dispose();
});

test("backup now creates an encrypted, verified backup visible on the backups page", async ({ page }) => {
  const api = await apiAs();
  const sw = await firstSimulatedSwitch(api, 1);
  await login(page);
  await page.goto(`/switches/${sw.id}?tab=configuration`);
  await page.getByRole("button", { name: "Back up now" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Review impact" }).click();
  await dialog.getByRole("button", { name: "Apply change" }).click();
  await expect(dialog.getByText(/was created/)).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).first().click();
  await expect
    .poll(async () => (await (await api.get("/api/v1/backups", { params: { switch_id: sw.id } })).json()).items[0]?.verify_status, { timeout: 30_000 })
    .toBe("verified");
  await page.goto(`/backups?switch_id=${sw.id}`);
  await expect(page.getByText("verified").first()).toBeVisible();
  await api.dispose();
});
