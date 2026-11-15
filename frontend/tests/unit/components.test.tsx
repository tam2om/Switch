import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PortPanel, portState } from "@/components/PortPanel";
import { SchemaForm, defaultsFor } from "@/components/SchemaForm";
import { ConfirmDialog, SimBadge, StaleBadge } from "@/components/ui";
import type { JsonSchema } from "@/lib/types";
import { makePort } from "./fixtures";

describe("PortPanel", () => {
  const ports = Array.from({ length: 28 }, (_, i) => makePort(i + 1));
  ports[2] = makePort(3, { oper_up: false });
  ports[3] = makePort(4, { admin_up: false, oper_up: false });
  ports[4] = makePort(5, { in_errors: 12 });
  ports[5] = makePort(6, { poe: { enabled: true, priority: "low", allocation_method: "usage", allocated_power_w: 30, power_drawn_w: 0, detection_status: "fault", power_class: null, fault: "overload", updated_at: null } });

  it("derives port state", () => {
    expect(portState(ports[0])).toBe("up");
    expect(portState(ports[2])).toBe("down");
    expect(portState(ports[3])).toBe("disabled");
    expect(portState(ports[4])).toBe("errors");
    expect(portState(ports[5])).toBe("fault");
  });

  it("renders all 28 ports with odd ports on top and toggles selection", async () => {
    const toggled: string[] = [];
    render(<PortPanel ports={ports} selected={new Set(["2"])} onToggle={(n) => toggled.push(n)} />);
    expect(screen.getAllByRole("button", { name: /^Port \d+,/ })).toHaveLength(28);
    expect(screen.getByRole("button", { name: "Port 2, Up" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Port 4, Administratively disabled" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Port 6, PoE fault" }));
    expect(toggled).toEqual(["6"]);
  });
});

describe("SchemaForm", () => {
  const schema: JsonSchema = {
    type: "object",
    required: ["ports", "enabled"],
    properties: {
      ports: { type: "array", items: { type: "string" }, title: "Ports" },
      enabled: { type: "boolean", title: "Enabled" },
      priority: { anyOf: [{ type: "string", enum: ["low", "high", "critical"] }, { type: "null" }], default: null, title: "Priority" },
      key: { type: "string", title: "Key", format: "password" },
      vlans: { type: "array", items: { type: "integer" }, title: "Vlans" },
    },
  };

  it("computes defaults", () => {
    expect(defaultsFor(schema)).toEqual({ ports: [], enabled: false, priority: null, vlans: [] });
  });

  it("parses port ranges, enums and integer lists into typed values", async () => {
    let values: Record<string, unknown> = defaultsFor(schema);
    const onChange = (v: Record<string, unknown>) => {
      values = v;
      rerender(<SchemaForm schema={schema} values={values} onChange={onChange} />);
    };
    const { rerender } = render(<SchemaForm schema={schema} values={values} onChange={onChange} />);
    const ports = screen.getByLabelText("Ports *");
    await userEvent.type(ports, "1-3, 9");
    fireEvent.blur(ports);
    expect(values.ports).toEqual(["1", "2", "3", "9"]);
    await userEvent.selectOptions(screen.getByLabelText("Priority"), "high");
    expect(values.priority).toBe("high");
    expect(screen.getByLabelText("Key")).toHaveAttribute("type", "password");
    const vlans = screen.getByLabelText("VLANs");
    await userEvent.type(vlans, "10,20");
    fireEvent.blur(vlans);
    expect(values.vlans).toEqual([10, 20]);
  });

  it("hides locked parameters", () => {
    render(<SchemaForm schema={schema} values={defaultsFor(schema)} onChange={() => undefined} hidden={["ports"]} />);
    expect(screen.queryByLabelText("Ports *")).toBeNull();
  });
});

describe("ConfirmDialog", () => {
  it("requires the exact confirmation text before confirming", async () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog open title="Remove switch" message="sure?" typeToConfirm="CORE-1" confirmLabel="Remove" onConfirm={onConfirm} onClose={() => undefined} />);
    const btn = screen.getByRole("button", { name: "Remove" });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Confirmation text"), "core-1");
    expect(btn).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("Confirmation text"));
    await userEvent.type(screen.getByLabelText("Confirmation text"), "CORE-1");
    expect(btn).toBeEnabled();
    await userEvent.click(btn);
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});

describe("data quality badges", () => {
  it("labels simulated devices and stale data", () => {
    render(
      <>
        <SimBadge show />
        <StaleBadge at="2020-01-01T00:00:00Z" stale />
        <StaleBadge at={null} stale={false} />
      </>,
    );
    expect(screen.getByText("SIMULATED")).toBeInTheDocument();
    expect(screen.getByText(/^stale/)).toBeInTheDocument();
    expect(screen.getByText("no data")).toBeInTheDocument();
  });
});
