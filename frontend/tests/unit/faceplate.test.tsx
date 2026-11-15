import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FaceplateLabel } from "@/components/switch/PortsTab";
import { ToastProvider } from "@/components/ui";
import { makePort } from "./fixtures";

describe("FaceplateLabel", () => {
  afterEach(() => vi.restoreAllMocks());

  it("is read-only without permission", () => {
    render(<FaceplateLabel switchId={1} port={makePort(3, { faceplate_label: "PP1-03" })} canEdit={false} onSaved={() => undefined} />);
    expect(screen.getByText("PP1-03")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Edit faceplate label/ })).toBeNull();
  });

  it("saves a trimmed label and rejects characters the server does not accept", async () => {
    const calls: { url: string; method?: string; body: unknown }[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      calls.push({ url: String(input), method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify({ port: "A3", faceplate_label: "R2-17" }), { status: 200, headers: { "content-type": "application/json" } });
    });
    const onSaved = vi.fn();
    render(
      <ToastProvider>
        <FaceplateLabel switchId={7} port={makePort(3, { name: "A3" })} canEdit onSaved={onSaved} />
      </ToastProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Edit faceplate label of port A3" }));
    const input = screen.getByRole("textbox", { name: "Faceplate label of port A3" });
    await userEvent.type(input, "bad;");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.clear(input);
    await userEvent.type(input, " R2-17 ");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(calls[0]).toEqual({ url: "/api/v1/switches/7/ports/A3/faceplate-label", method: "PUT", body: { faceplate_label: "R2-17" } });
  });
});
