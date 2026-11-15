import { render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import { AppShell } from "@/components/AppShell";
import { ToastProvider } from "@/components/ui";
import { MockAuthProvider } from "@/lib/auth";
import type { RoleName } from "@/lib/types";
import { makeMe } from "./fixtures";

function renderAs(role: RoleName, mode: "simple" | "pro" = "simple") {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({ items: [], total: 0, page: 1 }), { status: 200, headers: { "content-type": "application/json" } }));
  return render(
    <SWRConfig value={{ provider: () => new Map() }}>
      <MockAuthProvider value={{ me: makeMe(role), mode }}>
        <ToastProvider>
          <AppShell>
            <p>content</p>
          </AppShell>
        </ToastProvider>
      </MockAuthProvider>
    </SWRConfig>,
  );
}

describe("navigation is filtered by role", () => {
  afterEach(() => vi.restoreAllMocks());

  it("viewer sees monitoring pages only", () => {
    renderAs("viewer");
    for (const label of ["Dashboard", "Switches", "VLANs", "PoE", "Topology", "Monitoring & reports"]) expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    for (const label of ["Users", "Changes & approvals", "Bulk change", "Configuration backups", "Device credentials", "Audit log", "Alerts & events", "Connected devices"])
      expect(screen.queryByRole("link", { name: label })).toBeNull();
  });

  it("monitor additionally sees alerts and devices but no operations", () => {
    renderAs("monitor");
    expect(screen.getByRole("link", { name: "Alerts & events" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connected devices" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Bulk change" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Users" })).toBeNull();
  });

  it("admin sees operations and user management but not credentials or integrations", () => {
    renderAs("admin");
    for (const label of ["Changes & approvals", "Bulk change", "Configuration backups", "Users", "Audit log", "System health"]) expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Device credentials" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Integrations" })).toBeNull();
  });

  it("super admin sees every section", () => {
    renderAs("super_admin");
    for (const label of ["Device credentials", "Integrations", "Settings & polling", "Audit log"]) expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
  });

  it("shows the simulator banner and the current role", () => {
    renderAs("monitor");
    expect(screen.getByText(/Simulator mode is enabled/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My profile" })).toHaveTextContent("Monitor");
  });
});
