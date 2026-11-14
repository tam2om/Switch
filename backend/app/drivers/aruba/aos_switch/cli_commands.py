"""Allow-listed AOS-Switch CLI command builders.

Users never type CLI. Every command is produced from validated, typed parameters. Any value that could carry
command separators, quotes or control characters is rejected, which prevents command injection over SSH and
over the REST /cli resource.
"""

from __future__ import annotations

import re

from app.drivers.base import DriverError

PORT_RE = re.compile(r"^(?:[A-H]?\d{1,2}|Trk\d{1,3})$")
DESCRIPTION_RE = re.compile(r"^[A-Za-z0-9 _.,:/()#@+\-]{0,64}$")
VLAN_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")
HOST_RE = re.compile(r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9.\-]{1,253})$")
SNMP_USER_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")
SPEED_MODES = {"auto", "10-half", "10-full", "100-half", "100-full", "1000-full", "auto-10", "auto-100",
               "auto-1000", "auto-10-100"}
POE_PRIORITIES = {"low", "high", "critical"}
POE_ALLOC = {"usage", "class", "value"}


class CommandValidationError(DriverError, ValueError):
    def __init__(self, message: str):
        super().__init__("invalid_parameter", message, protocol="cli")


def port(p: str) -> str:
    if not isinstance(p, str) or not PORT_RE.match(p):
        raise CommandValidationError(f"Invalid port identifier: {p!r}")
    return p


def vlan_id(v: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 4094:
        raise CommandValidationError(f"VLAN ID must be an integer between 1 and 4094: {v!r}")
    return v


def description(d: str) -> str:
    if not isinstance(d, str) or not DESCRIPTION_RE.match(d):
        raise CommandValidationError("Description may contain letters, digits, spaces and _.,:/()#@+- (max 64)")
    return d


def vlan_name(n: str) -> str:
    if not isinstance(n, str) or not VLAN_NAME_RE.match(n):
        raise CommandValidationError("VLAN name may contain letters, digits and _.- (1-32 characters)")
    return n


def quote(s: str) -> str:
    return f'"{s}"'


def cmd_port_admin(p: str, enabled: bool) -> list[str]:
    return [f"interface {port(p)}", "enable" if enabled else "disable", "exit"]


def cmd_port_description(p: str, d: str) -> list[str]:
    d = description(d)
    return [f"interface {port(p)}", f"name {quote(d)}" if d else "no name", "exit"]


def cmd_port_speed(p: str, mode: str) -> list[str]:
    if mode not in SPEED_MODES:
        raise CommandValidationError(f"Unsupported speed-duplex mode: {mode!r}")
    return [f"interface {port(p)}", f"speed-duplex {mode}", "exit"]


def cmd_vlan_create(v: int, name: str) -> list[str]:
    return [f"vlan {vlan_id(v)}", f"name {quote(vlan_name(name))}", "exit"]


def cmd_vlan_delete(v: int) -> list[str]:
    if vlan_id(v) == 1:
        raise CommandValidationError("The default VLAN 1 cannot be deleted")
    return [f"no vlan {v}"]


def cmd_port_vlan(p: str, v: int, mode: str) -> list[str]:
    if mode not in ("tagged", "untagged"):
        raise CommandValidationError("mode must be tagged or untagged")
    return [f"vlan {vlan_id(v)}", f"{mode} {port(p)}", "exit"]


def cmd_port_vlan_remove(p: str, v: int, mode: str) -> list[str]:
    if mode not in ("tagged", "untagged"):
        raise CommandValidationError("mode must be tagged or untagged")
    return [f"vlan {vlan_id(v)}", f"no {mode} {port(p)}", "exit"]


def cmd_poe(p: str, enabled: bool | None, priority: str | None, alloc: str | None, value: float | None) -> list[str]:
    lines = [f"interface {port(p)}"]
    if enabled is not None:
        lines.append("power-over-ethernet" if enabled else "no power-over-ethernet")
    if priority is not None:
        if priority not in POE_PRIORITIES:
            raise CommandValidationError("PoE priority must be low, high or critical")
        lines.append(f"power-over-ethernet {priority}")
    if alloc is not None:
        if alloc not in POE_ALLOC:
            raise CommandValidationError("PoE allocation must be usage, class or value")
        if alloc == "value":
            if value is None or not 1 <= float(value) <= 30:
                raise CommandValidationError("PoE allocated value must be between 1 and 30 W (PoE+)")
            lines.append(f"power-over-ethernet allocate-by value {int(value)}")
        else:
            lines.append(f"power-over-ethernet allocate-by {alloc}")
    lines.append("exit")
    return lines


def cmd_poe_restart(p: str) -> list[list[str]]:
    p = port(p)
    return [[f"interface {p}", "no power-over-ethernet", "exit"], [f"interface {p}", "power-over-ethernet", "exit"]]


# ---- security / management features (allow-listed) ----

def cmd_sntp(servers: list[str], timezone_minutes: int | None = None) -> list[str]:
    if not servers or len(servers) > 3:
        raise CommandValidationError("Provide 1-3 SNTP servers")
    lines = ["timesync sntp", "sntp unicast"]
    for i, s in enumerate(servers, start=1):
        if not HOST_RE.match(s):
            raise CommandValidationError(f"Invalid SNTP server: {s!r}")
        lines.append(f"sntp server priority {i} {s}")
    if timezone_minutes is not None:
        if not -720 <= int(timezone_minutes) <= 840:
            raise CommandValidationError("Time zone offset out of range")
        lines.append(f"time timezone {int(timezone_minutes)}")
    return lines


def cmd_snmpv3_user(user: str, auth_proto: str, auth_pass: str, priv_proto: str, priv_pass: str,
                    access: str = "ro") -> list[str]:
    if not SNMP_USER_RE.match(user):
        raise CommandValidationError("Invalid SNMPv3 user name")
    if auth_proto != "sha" or priv_proto != "aes":  # MD5 and DES are not permitted
        raise CommandValidationError("Use SHA authentication and AES privacy")
    for secret in (auth_pass, priv_pass):
        if not re.match(r"^[A-Za-z0-9!#$%&*+,\-./:=?@^_~]{8,32}$", secret):
            raise CommandValidationError("SNMPv3 passphrases must be 8-32 characters without quotes or spaces")
    group = "operatorauth" if access == "ro" else "managerpriv"
    return [
        "snmpv3 enable",
        f"snmpv3 user {user} auth {auth_proto} {auth_pass} priv {priv_proto} {priv_pass}",
        f"snmpv3 group {group} user {user} sec-model ver3",
    ]


def cmd_ip_authorized_manager(network: str, mask: str, access: str = "manager") -> list[str]:
    for v in (network, mask):
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", v):
            raise CommandValidationError("Invalid IPv4 address or mask")
    if access not in ("manager", "operator"):
        raise CommandValidationError("access must be manager or operator")
    return [f"ip authorized-managers {network} {mask} access {access}"]


def cmd_port_security(p: str, learn_mode: str, address_limit: int, action: str) -> list[str]:
    if learn_mode not in ("continuous", "static", "configured", "port-access", "limited-continuous"):
        raise CommandValidationError("Invalid port-security learn mode")
    if not 1 <= int(address_limit) <= 64:
        raise CommandValidationError("Address limit must be 1-64")
    if action not in ("none", "send-alarm", "send-disable"):
        raise CommandValidationError("Invalid port-security action")
    return [f"port-security {port(p)} learn-mode {learn_mode} address-limit {int(address_limit)} action {action}"]


def cmd_stp_protection(ports: list[str], bpdu_protection: bool, admin_edge: bool) -> list[str]:
    plist = ",".join(port(p) for p in ports)
    lines = []
    if admin_edge:
        lines.append(f"spanning-tree {plist} admin-edge-port")
    lines.append(f"spanning-tree {plist} bpdu-protection" if bpdu_protection
                 else f"no spanning-tree {plist} bpdu-protection")
    return lines


def cmd_dhcp_snooping(enabled: bool, vlans: list[int], trusted_ports: list[str]) -> list[str]:
    if not enabled:
        return ["no dhcp-snooping"]
    vl = ",".join(str(vlan_id(v)) for v in vlans)
    lines = ["dhcp-snooping", f"dhcp-snooping vlan {vl}"]
    for p in trusted_ports:
        lines.append(f"dhcp-snooping trust {port(p)}")
    return lines


def cmd_radius_server(host: str, key: str) -> list[str]:
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        raise CommandValidationError("RADIUS server must be an IPv4 address")
    if not re.match(r"^[A-Za-z0-9!#$%&*+,\-./:=?@^_~]{8,64}$", key):
        raise CommandValidationError("RADIUS key must be 8-64 characters without quotes or spaces")
    return [f"radius-server host {host} key {key}"]


def cmd_tacacs_server(host: str, key: str) -> list[str]:
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        raise CommandValidationError("TACACS+ server must be an IPv4 address")
    if not re.match(r"^[A-Za-z0-9!#$%&*+,\-./:=?@^_~]{8,64}$", key):
        raise CommandValidationError("TACACS+ key must be 8-64 characters without quotes or spaces")
    return [f"tacacs-server host {host} key {key}"]


def cmd_ssh_hardening() -> list[str]:
    return ["ip ssh", "no telnet-server", "no web-management plaintext", "ip ssh filetransfer"]


ALLOWED_SHOW_COMMANDS = {
    "show running-config", "show config", "show system", "show system temperature", "show version",
    "show interfaces brief", "show vlans", "show power-over-ethernet brief", "show mac-address",
    "show lldp info remote-device", "show ip ssh", "show snmpv3 enable",
}


def assert_safe_line(line: str) -> str:
    """Final guard on every line sent to a device."""
    if any(c in line for c in ("\n", "\r", ";", "|", "`", "\x00")) or len(line) > 256:
        raise CommandValidationError("Unsafe characters in generated command")
    return line
