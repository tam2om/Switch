import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SWRConfig } from "swr";
import { ChangeDialog } from "@/components/ChangeDialog";
import { ToastProvider } from "@/components/ui";
import { MockAuthProvider } from "@/lib/auth";
import { makeMe } from "./fixtures";

const OPS = [
  {
    name: "config_restore",
    title: "Restore configuration backup",
    permission: "config.restore",
    allowed: true,
    bulk: false,
    warning: "The backup is written to the startup-config.",
    schema: { type: "object", required: ["backup_id"], properties: { backup_id: { type: "integer", title: "Backup Id" } } },
  },
];

const PREVIEW = {
  operation: "config_restore",
  title: "Restore backup #7",
  risk: "critical",
  reasons: ["Restoring replaces the whole configuration"],
  requires_approval: true,
  requires_acknowledgement: true,
  warning: "Reboot required",
  takes_backup: true,
  switches: [{ switch_id: 3, hostname: "SIM-SW-003", risk: "critical", reasons: ["Restoring replaces the whole configuration"], simulated: true }],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("ChangeDialog", () => {
  afterEach(() => vi.restoreAllMocks());

  it("previews risk server-side and requires acknowledgement for critical changes before submitting", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith("/operations")) return json(OPS);
      if (url.endsWith("/jobs/preview")) return json(PREVIEW);
      if (url.endsWith("/jobs")) return json({ id: 42, status: "pending_approval" }, 201);
      return json({}, 404);
    });
    const onCreated = vi.fn();
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <MockAuthProvider value={{ me: makeMe("admin") }}>
          <ToastProvider>
            <ChangeDialog request={{ operation: "config_restore", switchIds: [3], params: { backup_id: 7 }, lockedParams: ["backup_id"] }} onClose={() => undefined} onCreated={onCreated} />
          </ToastProvider>
        </MockAuthProvider>
      </SWRConfig>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Review impact" }));
    expect(await screen.findByText("Critical change")).toBeInTheDocument();
    expect(screen.getAllByText("SIMULATED").length).toBeGreaterThan(0);
    const submit = screen.getByRole("button", { name: "Submit for approval" });
    expect(submit).toBeDisabled();
    await userEvent.click(screen.getByLabelText(/I understand this change/));
    expect(submit).toBeEnabled();
    await userEvent.click(submit);
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    const create = calls.find((c) => c.url.endsWith("/jobs"))!;
    expect(create.body).toMatchObject({ operation: "config_restore", switch_ids: [3], params: { backup_id: 7 }, acknowledge_risk: true });
    expect(await screen.findByText(/second administrator must approve/)).toBeInTheDocument();
  });

  it("shows server validation errors instead of submitting", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/operations")) return json(OPS);
      return json({ detail: { code: "invalid_params", message: "Backup 7 belongs to another switch" } }, 400);
    });
    render(
      <SWRConfig value={{ provider: () => new Map() }}>
        <MockAuthProvider value={{ me: makeMe("admin") }}>
          <ToastProvider>
            <ChangeDialog request={{ operation: "config_restore", switchIds: [3], params: { backup_id: 7 } }} onClose={() => undefined} />
          </ToastProvider>
        </MockAuthProvider>
      </SWRConfig>,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Review impact" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Backup 7 belongs to another switch");
  });
});
