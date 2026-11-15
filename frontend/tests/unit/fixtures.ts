import type { Me, Port, RoleName } from "@/lib/types";

const PERMS: Record<RoleName, string[]> = {
  viewer: ["dashboard.view", "metrics.view", "poe.view", "port.view", "report.view", "switch.view", "topology.view", "vlan.view"],
  monitor: ["alert.ack", "alert.view", "dashboard.view", "device.view", "event.view", "metrics.view", "poe.view", "port.view", "report.export", "report.view", "switch.view", "topology.view", "vlan.view"],
  admin: [
    "alert.ack", "alert.view", "alert_rule.manage", "audit.view_operational", "backup.export", "backup.manage", "backup.view", "bulk.execute", "config.restore",
    "dashboard.view", "device.view", "event.view", "job.view", "metrics.view", "netsec.manage", "poe.manage", "poe.view", "port.manage", "port.view",
    "report.export", "report.view", "settings.operational", "settings.view", "switch.delete", "switch.manage", "switch.view", "system.health",
    "template.manage", "topology.view", "user.manage", "user.view", "vlan.manage", "vlan.view",
  ],
  super_admin: [],
};
PERMS.super_admin = [...PERMS.admin, "audit.view_all", "change.approve", "credential.manage", "integration.manage", "settings.manage", "user.manage_superadmin"];

export function makeMe(role: RoleName, extra: Partial<Me> = {}): Me {
  return {
    id: 1, username: `${role}-user`, full_name: "", email: null, role, is_active: true, mfa_enabled: false, must_change_password: false,
    last_login_at: null, last_login_ip: null, created_at: "2026-01-01T00:00:00Z", locked: false, preferences: {},
    permissions: PERMS[role], mfa_setup_required: false, simulator_enabled: true, dashboard_refresh_seconds: 30, stale_after_seconds: 180, ...extra,
  };
}

export function makePort(n: number, over: Partial<Port> = {}): Port {
  return {
    id: n, name: String(n), if_index: n, port_number: n, description: "", port_type: n > 24 ? "SFP+" : "10/100/1000T PoE+", is_uplink: n > 24,
    trunk_group: null, admin_up: true, oper_up: true, speed_mbps: 1000, duplex: "full", config_mode: "auto", untagged_vlan: 1, tagged_vlans: [],
    in_bps: 1000, out_bps: 1000, in_errors: 0, out_errors: 0, in_discards: 0, out_discards: 0, flap_count: 0, status_changed_at: null, updated_at: null,
    poe: null, macs: [], neighbors: [], ...over,
  };
}
