# Hardware compatibility

## Target

| Item | Value |
|---|---|
| Switch | Aruba 2540 24G PoE+ 4SFP+ (JL356A) |
| Also recognised | JL354A (2540 24G), JL355A (2540 48G), JL357A (2540 48G PoE+) |
| Also in the estate | Aruba 2930F-8G-PoE+-2SFP+ (JL258A), HP/HPE Aruba 5406R zl2 (J9850A); see "Other models" below |
| Firmware | YC.16.11.0018 (AOS-Switch 16.11 train) |
| REST API | v3 to v7; the driver reads `GET /rest/version` and uses the highest listed version up to v7 |
| SNMP | v3 authPriv only (SHA, SHA-256, SHA-512 / AES-128, AES-192, AES-256) |
| SSH | SSH v2, password authentication, trusted host key required |

## Evidence levels

* **documented**: implemented from the HPE/Aruba AOS-Switch 16.11 REST API, MIB and CLI references and tested
  against the simulator. **Not yet confirmed on a physical switch.**
* **verified**: confirmed on a physical 2540 running YC.16.11.0018, with a reviewed report from the procedure in
  [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).
* **unsupported**: known to be unavailable; the operation is refused.

**Every capability below is "documented". None is "verified".** No physical switch was available during
development. The application can be used with real switches only after the validation procedure has been run on a
lab switch.

At runtime the driver also probes each REST resource on every switch and records which ones answered, so a
resource that the firmware does not provide is not used and its fallback is used instead (visible on a switch's
Overview tab).

## Capability matrix (AOS-Switch 16.11)

Generated from `backend/app/drivers/aruba/aos_switch/capabilities.py`
(also available in the application under Administration → System health and at `GET /api/v1/capabilities/matrix`, together with how many real switches answered each REST resource).

| Capability | Protocol | Resource | Write | Fallback | Evidence | Notes |
|---|---|---|:-:|---|---|---|
| `rest.login` | REST | POST /login-sessions |  |  | documented |  |
| `system.read` | REST | GET /system/status |  | `snmp.system` | documented |  |
| `snmp.system` | SNMP | SNMPv2-MIB::system (1.3.6.1.2.1.1) |  |  | documented |  |
| `health.cpu` | SNMP | STATISTICS-MIB::hpSwitchCpuStat 1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0 |  |  | documented |  |
| `health.memory` | SNMP | NETSWITCH-MIB::hpLocalMemTotalBytes/FreeBytes 1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1 |  |  | documented |  |
| `health.temperature` | SNMP | ENTITY-SENSOR-MIB::entPhySensorValue (type celsius) |  |  | documented | Sensors reading 0 or not ok are ignored; falls back to `show system temperature`; shown as n/a otherwise |
| `ports.read` | REST | GET /ports |  | `snmp.ifmib` | documented |  |
| `snmp.ifmib` | SNMP | IF-MIB ifTable/ifXTable |  |  | documented |  |
| `ports.counters` | SNMP | IF-MIB ifHCInOctets/ifHCOutOctets/ifInErrors/... |  |  | documented |  |
| `ports.admin` | REST | PUT /ports/{id} is_port_enabled | yes | `cli.interface` | documented |  |
| `ports.description` | REST | PUT /ports/{id} name | yes | `cli.interface` | documented |  |
| `ports.speed_duplex` | REST | PUT /ports/{id} config_mode | yes | `cli.interface` | documented |  |
| `vlans.read` | REST | GET /vlans |  | `snmp.qbridge` | documented |  |
| `snmp.qbridge` | SNMP | Q-BRIDGE-MIB dot1qVlanStaticTable |  |  | documented |  |
| `vlans.write` | REST | POST/PUT/DELETE /vlans | yes | `cli.vlan` | documented |  |
| `vlan_ports.read` | REST | GET /vlans-ports |  | `snmp.vlan_ports` | documented |  |
| `snmp.vlan_ports` | SNMP | Q-BRIDGE-MIB dot1qVlanStaticEgressPorts/UntaggedPorts (current table if empty) |  |  | documented | Parsing checked against a recorded walk of a JL356A on YC.16.11.0018 |
| `vlan_ports.write` | REST | POST/DELETE /vlans-ports | yes | `cli.vlan` | documented |  |
| `poe.read` | REST | GET /poe/ports |  | `snmp.poe_ports` | documented |  |
| `snmp.poe_ports` | SNMP | POWER-ETHERNET-MIB pethPsePortTable + HP-ICF-POE-MIB port power (mW) and allocate-by |  |  | documented | Matches `show power-over-ethernet brief` on a JL356A; allocated power value is REST-only |
| `poe.stats` | REST | GET /poe/ports/stats |  |  | documented |  |
| `poe.summary` | SNMP | POWER-ETHERNET-MIB pethMainPseTable 1.3.6.1.2.1.105.1.3.1.1 |  |  | documented |  |
| `poe.write` | REST | PUT /poe/ports/{id} | yes | `cli.interface` | documented |  |
| `poe.restart` | SSH | interface <p> no power-over-ethernet ; interface <p> power-over-ethernet | yes |  | documented | Implemented as disable/enable of PoE on the port; disconnects the powered device |
| `mac.read` | REST | GET /mac-table |  | `snmp.fdb` | documented |  |
| `snmp.fdb` | SNMP | Q-BRIDGE-MIB dot1qTpFdbPort |  |  | documented |  |
| `lldp.read` | REST | GET /lldp/remote-device |  | `snmp.lldp` | documented |  |
| `snmp.lldp` | SNMP | LLDP-MIB lldpRemTable 1.0.8802.1.1.2.1.4.1 |  |  | documented |  |
| `config.running` | REST | POST /cli {cmd: 'show running-config'} |  | `ssh.show_run` | documented |  |
| `ssh.show_run` | SSH | show running-config |  |  | documented |  |
| `config.startup` | SSH | show config |  |  | documented |  |
| `config.upload_startup` | SSH | SFTP put /cfg/startup-config | yes |  | documented | Requires 'ip ssh filetransfer' on the switch; activation requires a reload |
| `config.write_memory` | REST | POST /cli {cmd: 'write memory'} | yes | `ssh.write_mem` | documented |  |
| `ssh.write_mem` | SSH | write memory | yes |  | documented |  |
| `cli.interface` | SSH | interface <p> (enable\|disable\|name\|speed-duplex\|power-over-ethernet) | yes |  | documented |  |
| `cli.vlan` | SSH | vlan <id> (name\|tagged\|untagged\|no) | yes |  | documented |  |
| `cli.security` | SSH | allow-listed security commands (see cli_commands.py) | yes |  | documented |  |

## Change operations and how they are applied

| Operation | Preferred path | Fallback | Verified by read-back |
|---|---|---|---|
| Port enable/disable, description, speed/duplex | REST `PUT /ports/{id}` | SSH `interface` commands | yes |
| Port VLAN (tagged/untagged), VLAN create/rename/delete | REST `/vlans`, `/vlans-ports` | SSH `vlan` commands | yes |
| PoE enable, priority, allocation | REST `PUT /poe/ports/{id}` | SSH `interface ... power-over-ethernet` | yes |
| PoE restart | SSH (disable then enable PoE) | none | yes |
| SNTP, SNMPv3 user, authorized managers, port security, STP protection, DHCP snooping, AAA server, SSH hardening | SSH, allow-listed commands generated from typed parameters | none | yes (running-config) |
| Save configuration | REST `POST /cli write memory` | SSH `write memory` | n/a |
| Configuration backup | REST `POST /cli show running-config` | SSH `show running-config` | SHA-256 + decrypt check |
| Configuration restore | SFTP upload of startup-config (needs `ip ssh filetransfer`) | none | startup-config compared with the backup |

Read commands allowed over SSH: `show running-config`, `show config`, `show system`, `show system temperature`,
`show version`, `show interfaces brief`, `show vlans`, `show power-over-ethernet brief`, `show mac-address`,
`show lldp info remote-device`, `show ip ssh`, `show snmpv3 enable`.

## Other models

All of these run AOS-Switch 16.x, so they use the same driver and the same capability registry as the 2540. The model
is detected from the product number the switch reports (REST `/system/status` or SNMP `sysDescr`); nothing is
assumed from inventory. The catalogue is in `backend/app/drivers/aruba/aos_switch/models.py`.

| Model | Product numbers | Firmware train | Ports | PoE | Status |
|---|---|---|---|---|---|
| Aruba 2930F-8G-PoE+-2SFP+ | JL258A | WC.16.x | 1-8 copper PoE+, 9-10 SFP+ | 125 W budget | documented, simulated |
| Aruba 2930F (other sizes) | JL253A-JL256A, JL259A-JL262A | WC.16.x | 24/48 copper + 4 SFP or SFP+ | 370 W on PoE models | documented |
| HPE Aruba 5406R zl2 | J9850A, J9821A | KB.16.x | slot ports A1-F24, depends on modules | from the device (power supplies) | documented, simulated |
| HPE Aruba 5412R zl2 | J9851A, J9822A | KB.16.x | slot ports A1-L24 | from the device | documented |

How the application handles them:

* **Port naming.** Fixed-port switches use numbers (1, 2, ... 10). The 5400R uses the slot letter plus the port
  (A1, B24). Port identifiers A1-L24, 1-52 and trunks Trk1.. are accepted by every typed operation; anything else is
  rejected before a command is built. Port lists are shown in natural order (A1, A2 ... A24, B1).
* **Front-panel view.** Fixed-port models show odd/even rows with the SFP/SFP+ uplinks on the right. The 5400R
  shows one block per module slot.
* **Port type.** Taken from the model catalogue on fixed-port switches (copper PoE+ or SFP/SFP+). On the 5400R the
  module type is not read yet, so slot ports are shown as "PoE+" when the device reports PoE for them and are left
  blank otherwise (an SFP+ module port is not labelled SFP+).
* **PoE.** Budget and consumption come from POWER-ETHERNET-MIB, summed over all PSE rows (a chassis can report more
  than one). Per-port PoE comes from REST `/poe/ports` for whichever ports the device lists, or from
  POWER-ETHERNET-MIB when REST is not available. If a chassis numbers PoE ports per slot group instead of by
  ifIndex, group g / port n is mapped to the slot port (g-1)*24+n.
* **ifIndex.** Read from IF-MIB. If a port is first seen over REST only, the AOS-Switch convention (A1 = 1,
  B1 = 25, ...) is assumed until SNMP supplies the real value.
* **Not covered.** VSF/backplane stacking, chassis redundancy (dual management modules), module inventory and
  hot-swap events, power-supply and fan status, and per-module PoE budgets. Firmware other than 16.11 uses the 16.11
  registry; each REST resource is still probed per switch.

None of these models has been validated on hardware. The validation procedure in
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) applies to each model separately.

## Reading without REST (SNMPv3 only)

When a switch has no REST credential, or a REST resource is missing, every read has an SNMP source:

* VLAN port membership: Q-BRIDGE-MIB static egress/untagged bitmaps, mapped to port names through
  dot1dBasePortIfIndex and ifName. Bits for bridge ports that do not exist are ignored.
* Per-port PoE: enable, detection status, priority and class from POWER-ETHERNET-MIB; delivered power (mW) and
  allocation method from HP-ICF-POE-MIB. The allocated power value is only available over REST.

SNMP stays read-only. Changes still need REST or SSH configuration credentials. Both parsers were checked against a
read-only walk of a JL356A on YC.16.11.0018 (`backend/tests/fixtures/`) and its CLI output. This confirms the
parsing only. It is not a full hardware validation.

## Items with known uncertainty on real hardware

* Temperature: checked on a JL356A (YC.16.11.0018). Its only celsius sensor in ENTITY-SENSOR-MIB ("Chassis Sensor")
  always reads 0 with status ok, and `show system temperature` is not a valid command on that firmware, so the switch
  has no temperature reading and the UI shows "n/a". A sensor reading 0, or with a status other than ok, is never
  shown as a temperature.
* REST: on YC.16.11.0018 `GET /rest/version` answers HTTP 400 "Please login to access the resource" before a session
  exists. The driver treats that as REST present and logs in with v7.
* REST `POST /cli` availability and output format on YC.16.11.0018 must be confirmed; SSH is the fallback.
* Concurrent REST session limits per switch: the client always logs out, but the limit must be checked under load.
* Exact CLI syntax of the security operations must be checked against the 16.11 CLI on a lab switch before use.
