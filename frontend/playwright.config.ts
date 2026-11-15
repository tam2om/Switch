import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a live stack (backend + simulator + frontend).
// E2E_BASE_URL defaults to the Next dev server, which proxies /api to the backend.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:3000",
    trace: "off",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
