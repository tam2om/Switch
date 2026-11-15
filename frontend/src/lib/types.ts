// Response shapes of the backend API (see backend/app/api).

export type RoleName = "super_admin" | "admin" | "monitor" | "viewer";
export type Theme = "dark" | "light";
export type Mode = "simple" | "pro";

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: RoleName;
  is_active: boolean;
  mfa_enabled: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  last_login_ip: string | null;
  created_at: string;
  locked: boolean;
  preferences: { theme?: Theme; mode?: Mode; refresh_seconds?: number };
  manageable?: boolean;
}

export interface Me extends User {
  permissions: string[];
  mfa_setup_required: boolean;
  simulator_enabled: boolean;
  dashboard_refresh_seconds: number;
  stale_after_seconds: number;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size?: number;
}

export type SwitchStatus = "online" | "offline" | "warning" | "unknown" | "maintenance";

export interface SwitchMetrics {
  at: string | null;
  stale: boolean;
  uptime_seconds: number | null;
  cpu_pct: number | null;
  mem_pct: number | null;
  temperature_c: number | null;
  poe_budget_w: number | null;
  poe_consumed_w: number | null;
}

export interface SwitchRow {
  id: number;
  hostname: string;
  mgmt_ip: string;
  status: SwitchStatus;
  status_reason: string;
  is_simulated: boolean;
  driver: string;
  product_number: string | null;
  model_name: string | null;
  model_verified: boolean;
  serial_number: string | null;
  base_mac: string | null;
  firmware: string | null;
  rom_version: string | null;
  site_id: number | null;
  site: string | null;
  location: string;
  building: string;
  floor: string;
  department: string;
  mgmt_vlan: number | null;
  uplink_ports: string[];
  monitoring_enabled: boolean;
  protocols: { ssh?: boolean; rest?: boolean; snmp?: boolean };
  rest_api_version: string | null;
  last_poll_at: string | null;
  last_success_at: string | null;
  poll_stale: boolean;
  metrics: SwitchMetrics | null;
  capabilities: {
    ssh?: boolean;
    rest?: boolean;
    snmp?: boolean;
    errors?: string[];
    probed_at?: string;
    resources?: Record<string, boolean>;
  };
  ssh_host_key_fingerprint: string | null;
  ssh_host_key_trusted: boolean;
}

export interface SwitchDetail extends SwitchRow {
  notes: string;
  external_ids: Record<string, unknown>;
  groups: { id: number; name: string }[];
  created_at: string;
  updated_at: string;
  ports_total: number;
  ports_up: number;
  vlan_count: number;
}

export interface PoePort {
  port?: string;
  enabled: boolean;
  priority: string;
  allocation_method: string;
  allocated_power_w: number | null;
  power_drawn_w: number | null;
  detection_status: string;
  power_class: string | null;
  fault: string | null;
  updated_at: string | null;
}

export interface Neighbor {
  id: number;
  local_port: string;
  chassis_id: string;
  remote_port: string;
  remote_port_desc: string;
  system_name: string;
  system_description: string;
  mgmt_address: string | null;
  capabilities: string[];
  remote_switch_id: number | null;
  source: string;
  first_seen: string;
  last_seen: string;
}

export interface MacEntry {
  mac: string;
  vlan_id: number | null;
  vendor?: string | null;
  last_seen?: string;
}

export interface Port {
  id: number;
  name: string;
  if_index: number;
  port_number: number | null;
  description: string;
  /** Patch-panel / wall-jack label, stored in the application only. */
  faceplate_label: string;
  port_type: string;
  is_uplink: boolean;
  trunk_group: string | null;
  admin_up: boolean;
  oper_up: boolean;
  speed_mbps: number | null;
  duplex: string | null;
  config_mode: string;
  untagged_vlan: number | null;
  tagged_vlans: number[];
  in_bps: number | null;
  out_bps: number | null;
  in_errors: number;
  out_errors: number;
  in_discards: number;
  out_discards: number;
  flap_count: number;
  status_changed_at: string | null;
  updated_at: string | null;
  poe: PoePort | null;
  macs: MacEntry[];
  neighbors: { system_name: string; remote_port: string; remote_switch_id: number | null }[];
}

export interface SwitchVlan {
  vlan_id: number;
  name: string;
  status: string;
  is_management: boolean;
  untagged_ports: string[];
  tagged_ports: string[];
  updated_at: string;
}

export interface Operation {
  name: string;
  title: string;
  permission: string;
  allowed: boolean;
  bulk: boolean;
  warning: string;
  schema: JsonSchema;
}

export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  enum?: (string | number)[];
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  minItems?: number;
  maxItems?: number;
  format?: string;
  writeOnly?: boolean;
  const?: unknown;
}

export type Risk = "low" | "medium" | "high" | "critical";

export interface Preview {
  operation: string;
  title: string;
  risk: Risk;
  reasons: string[];
  requires_approval: boolean;
  requires_acknowledgement: boolean;
  warning: string;
  takes_backup: boolean;
  switches: { switch_id: number; hostname: string; risk: Risk; reasons: string[]; simulated: boolean }[];
}

export type JobStatus =
  | "pending_approval"
  | "queued"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "rejected"
  | "stopped";

export interface JobResult {
  id: number;
  switch_id: number;
  hostname: string | null;
  batch_index: number;
  status: string;
  attempts: number;
  pre_backup_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  message: string;
  details: { steps?: { step: string; ok: boolean; [k: string]: unknown }[]; [k: string]: unknown };
}

export interface Job {
  id: number;
  operation: string;
  title: string;
  params: Record<string, unknown>;
  risk: Risk;
  risk_reasons: string[];
  status: JobStatus;
  requires_approval: boolean;
  requested_by: string | null;
  requested_by_id: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  batch_size: number;
  canary: boolean;
  max_failures: number;
  cancel_requested: boolean;
  summary: { counts?: Record<string, number>; stopped_reason?: string };
  error: string;
  target_count: number;
  progress: Record<string, number>;
  approvals: { approver: string; decision: string; comment: string; at?: string; created_at?: string }[];
  results?: JobResult[];
}

export interface Backup {
  id: number;
  switch_id: number;
  hostname: string | null;
  created_at: string;
  trigger: string;
  size_bytes: number;
  sha256: string;
  encrypted: boolean;
  source: string;
  verify_status: string;
  verified_at: string | null;
  restore_tested: boolean;
  restore_tested_at: string | null;
  job_id: number | null;
  note: string;
  firmware: string | null;
}

export interface Alert {
  id: number;
  type: string;
  severity: "critical" | "warning" | "info";
  status: "active" | "acknowledged" | "resolved";
  message: string;
  switch_id: number | null;
  hostname: string | null;
  port_name: string | null;
  first_seen: string;
  last_seen: string;
  occurrences: number;
  acknowledged_at: string | null;
  resolved_at: string | null;
  details: Record<string, unknown>;
}

export interface EventRow {
  id: number;
  ts: string;
  severity: string;
  type: string;
  message: string;
  switch_id: number | null;
  hostname: string | null;
  port_name: string | null;
}

export interface Setting {
  key: string;
  category: string;
  value: unknown;
  default: unknown;
  description: string;
  updated_at: string | null;
  editable: boolean;
}

export interface Site {
  id: number;
  name: string;
  address: string;
  description: string;
  switch_count: number;
}

export interface Group {
  id: number;
  name: string;
  description: string;
  switch_ids: number[];
}

export interface Credential {
  id: number;
  switch_id: number | null;
  name: string;
  kind: "rest" | "ssh" | "snmpv3";
  purpose: "monitor" | "config";
  username: string;
  params: Record<string, unknown>;
  secret: string;
  updated_at: string;
}

export interface PollingJob {
  category: string;
  interval_seconds: number;
  enabled: boolean;
  last_run_at: string | null;
  last_duration_ms: number | null;
  last_status: string;
  last_error: string;
  switches_polled: number;
  switches_failed: number;
}

export interface Integration {
  kind: "zabbix" | "airwave";
  enabled: boolean;
  url: string;
  username: string;
  has_secret: boolean;
  verify_tls: boolean;
  params: Record<string, unknown>;
  last_sync_at: string | null;
  last_status: string;
  last_message: string;
}

export interface AuditRow {
  id: number;
  ts: string;
  category: string;
  action: string;
  result: string;
  actor: string | null;
  target_type: string | null;
  target_id: string | null;
  switch_id: number | null;
  ip: string | null;
  details: Record<string, unknown>;
}
