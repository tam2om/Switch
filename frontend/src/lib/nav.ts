import {
  Activity, Archive, Bell, Boxes, Cable, ClipboardList, Gauge, KeyRound, Network, Plug, Server, Settings,
  ShieldCheck, Share2, Users, Waypoints, Zap, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** The item is shown when the user holds any of these permissions. */
  anyOf: string[];
  /** Hidden in Simple mode to keep the interface focused. */
  pro?: boolean;
}

export const NAV: { section: string; items: NavItem[] }[] = [
  {
    section: "Network",
    items: [
      { href: "/", label: "Dashboard", icon: Gauge, anyOf: ["dashboard.view"] },
      { href: "/switches", label: "Switches", icon: Server, anyOf: ["switch.view"] },
      { href: "/vlans", label: "VLANs", icon: Waypoints, anyOf: ["vlan.view"] },
      { href: "/poe", label: "PoE", icon: Zap, anyOf: ["poe.view"] },
      { href: "/devices", label: "Connected devices", icon: Cable, anyOf: ["device.view"] },
      { href: "/topology", label: "Topology", icon: Share2, anyOf: ["topology.view"] },
      { href: "/monitoring", label: "Monitoring & reports", icon: Activity, anyOf: ["metrics.view", "report.view"] },
      { href: "/alerts", label: "Alerts & events", icon: Bell, anyOf: ["alert.view", "event.view"] },
    ],
  },
  {
    section: "Operations",
    items: [
      { href: "/changes", label: "Changes & approvals", icon: ClipboardList, anyOf: ["job.view"] },
      { href: "/changes/new", label: "Bulk change", icon: Boxes, anyOf: ["bulk.execute"] },
      { href: "/backups", label: "Configuration backups", icon: Archive, anyOf: ["backup.view"] },
    ],
  },
  {
    section: "Administration",
    items: [
      { href: "/admin/users", label: "Users", icon: Users, anyOf: ["user.view"] },
      { href: "/admin/inventory", label: "Sites & groups", icon: Network, anyOf: ["switch.manage"] },
      { href: "/admin/credentials", label: "Device credentials", icon: KeyRound, anyOf: ["credential.manage"] },
      { href: "/admin/settings", label: "Settings & polling", icon: Settings, anyOf: ["settings.view"] },
      { href: "/admin/integrations", label: "Integrations", icon: Plug, anyOf: ["integration.manage"] },
      { href: "/admin/system", label: "System health", icon: Activity, anyOf: ["system.health"], pro: false },
      { href: "/admin/audit", label: "Audit log", icon: ShieldCheck, anyOf: ["audit.view_operational", "audit.view_all"] },
    ],
  },
];
