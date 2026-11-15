# User manual

## Signing in

Open the address your administrators gave you (for example `https://anm.example.internal/`). Sign in with your
username and password. If two-factor authentication is on for your account, enter the 6-digit code from your
authenticator app. After 5 wrong passwords the account is locked for 15 minutes.

Forgot your password? Ask an administrator for a one-time reset link and open it to set a new password.

If your role requires two-factor authentication and you have not set it up, the application takes you to your
profile until you do.

## What you can do depends on your role

| | Viewer | Monitor | Admin | Super Admin |
|---|---|---|---|---|
| Dashboard, switches, ports, VLANs, PoE, topology, metrics, reports | ✓ | ✓ | ✓ | ✓ |
| Connected devices (MAC tables), alerts and events, acknowledge alerts, export reports | | ✓ | ✓ | ✓ |
| Request changes (ports, VLANs, PoE, security features), bulk changes, backups, restore | | | ✓ | ✓ |
| Manage switches, sites and groups, alert rules, polling and backup schedule | | | ✓ | ✓ |
| Manage Monitor and Viewer users; operational audit log | | | ✓ | ✓ |
| Approve high-risk changes, manage all users, credentials, security settings, integrations, full audit log | | | | ✓ |

Menu items you cannot use are not shown. The server enforces the same rules, so a hidden page cannot be reached by
typing its address.

## Layout

* **Left menu**: the modules. **Top bar**: global search (switch name, IP, serial, MAC), the alert bell, theme
  (dark or light), and the interface mode.
* **Simple mode** shows the essentials. **Pro mode** adds columns and advanced options such as batch size and
  canary rollout for changes. Switch modes in the top bar or in My profile.
* Values that are older than the polling interval allows are marked **stale**. Simulated switches are marked
  **SIMULATED** and a banner is shown while the simulator is enabled.

## Dashboard

Fleet status at a glance: switches online/offline, ports up, PoE power used against budget, active alerts by
severity, recent changes, and the switches that need attention. It refreshes automatically (default every 30
seconds; change it in My profile).

## Switches

The list shows every switch with status, model, firmware, site, uptime, CPU, memory and PoE use. Filter by status,
site or group, or search. Open a switch to see its tabs:

* **Overview**: identity (model, serial, firmware, MAC), health, uptime, detected protocols (REST, SNMPv3, SSH) and
  capabilities.
* **Ports**: a front-panel view and a table with link state, speed, VLANs, PoE and errors. Admins can enable or
  disable a port, change its description, speed/duplex or VLANs.
* **Faceplate label**: on the Ports tab, the column between Port and Description holds the label of the
  patch-panel port or wall jack the switch port is cabled to (for example `PP1-03`). Super Admins and Admins can
  edit it with "edit". It is stored in the application only and is never written to the switch, so it needs no
  change job or approval. Polling does not change it, every edit is in the audit log, and you can search for it on
  the Ports tab and in Connected devices.
* **VLANs**, **PoE**: per-switch VLAN membership and per-port power.
* **Devices**: MAC addresses learned on each port, with vendor names.
* **Neighbours**: LLDP neighbours.
* **Monitoring**: CPU, memory, temperature, traffic and reachability charts for a chosen time range.
* **Configuration**: backups of this switch, differences between them, "Back up now".
* **Security**: management security settings (SNTP, SNMPv3 users, authorized managers, port security, STP
  protection, DHCP snooping, AAA servers, SSH hardening) with buttons to request changes.
* **Events**: what happened to this switch.

## VLANs, PoE, connected devices, topology

* **VLANs**: every VLAN across the fleet and where it is configured; create or delete a VLAN on many switches.
* **PoE**: power budget and consumption per switch and per port; enable, disable, prioritise or restart PoE on a
  port (restarting power-cycles the connected device).
* **Connected devices**: search a MAC address, vendor or port to find where a device is plugged in.
* **Topology**: the LLDP map of switches and their links.

## Monitoring and reports

Charts across the fleet and availability, bandwidth and port reports (daily, weekly, monthly). Monitors and above
can export a report as CSV.

## Alerts and events

Active alerts with severity (critical, major, warning, info): switch offline, port down or flapping, high errors,
high CPU, memory or PoE, PoE faults, new devices, unexpected configuration changes and failed operations.
Acknowledge an alert to show you are handling it; it resolves by itself when the condition clears.

## Making a change (Admin and Super Admin)

Every change goes through the same steps, whether it is one port or fifty switches:

1. Choose the action (from a port, a switch tab, or **Bulk change**) and fill in the form.
2. **Preview**: the application shows the risk level (low, medium, high, critical), the reasons, the switches
   affected, and the exact operations. Read it.
3. For a **critical** change you must tick the acknowledgement box.
4. **Submit**. If the risk is at or above the approval threshold (default: high), the change waits for a Super
   Admin's approval and has not touched any switch yet. You cannot approve your own change.
5. When it runs, each switch gets a pre-change backup, the change, a read-back check and a save to memory.
   High and critical changes run one switch at a time. In Pro mode you can set the batch size, run one switch first
   (canary) and stop after a number of failures.
6. Follow progress on **Changes & approvals**. Each switch shows its steps, its result and a link to its
   pre-change backup. You can cancel a queued change, stop a running one after the current switch, or retry only
   the switches that failed.

Passwords and keys entered in a change (for example an SNMPv3 user) are never shown again; they appear as
`********`.

## Configuration backups

Backups are taken daily (default 02:00), before every change, and on demand. Each one is encrypted and has an
integrity check. You can view a backup, compare two backups line by line, verify it, download it (if your role
allows) or restore it to the switch it came from. A restore replaces the startup configuration, so it is a critical change: it needs the risk acknowledgement and a
Super Admin's approval. The restored configuration becomes active only when the switch is reloaded, which you do
yourself in a maintenance window (the application never reloads switches). Do not save the running configuration
before that reload, or it overwrites the restored startup configuration.
The **Configuration drift** tab lists configuration changes found between backups and whether they were made
through this application or outside it.

## My profile

Change your password, set up two-factor authentication, choose theme, interface mode and refresh interval, and
see your active sessions (sign out the others if you see one you do not recognise).
