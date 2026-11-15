"""Simulated SSH CLI session. Accepts only the commands the real driver can generate."""

from __future__ import annotations

import re

from app.drivers.aruba.aos_switch.cli_commands import ALLOWED_SHOW_COMMANDS, assert_safe_line
from app.drivers.base import DriverError
from app.drivers.simulator import state as st


class SimSshSession:
    def __init__(self, ip: str, username: str, password: str, host_key_trusted: bool):
        sw = st.store.get(ip)
        if sw is None or sw.offline:
            raise DriverError("timeout", "SSH connection timed out", protocol="ssh", retriable=True)
        if not host_key_trusted:
            raise DriverError("host_key_untrusted", "SSH host key has not been trusted for this switch",
                              protocol="ssh")
        if username != "sim-ssh" or password != "sim-ssh-password":  # noqa: S105
            raise DriverError("auth_failed", "SSH authentication failed", protocol="ssh")
        self.ip = ip

    def show(self, command: str) -> str:
        if command not in ALLOWED_SHOW_COMMANDS:
            raise DriverError("not_allowed", f"Command not allow-listed: {command}", protocol="ssh")
        sw = st.store.get(self.ip)
        assert sw is not None
        if command == "show running-config":
            return "Running configuration:\n\n" + sw.running_config()
        if command == "show config":
            return "Startup configuration:\n\n" + (sw.startup_config or sw.running_config())
        if command == "show version":
            return f"Image stamp:\n  {sw.profile.firmware}\n"
        if command == "show system temperature":
            return f" System Temperature\n  Current: {sw.temperature()}C\n"
        return ""

    def configure(self, lines: list[str]) -> str:
        for line in lines:
            assert_safe_line(line)
        st.mutate(self.ip, lambda sw: _apply(sw, lines))
        return ""

    def put_file(self, remote_path: str, content: str) -> None:
        if remote_path != "/cfg/startup-config":
            raise DriverError("not_allowed", "Only /cfg/startup-config may be written", protocol="ssh")
        st.mutate(self.ip, lambda sw: setattr(sw, "startup_config", content))

    def close(self) -> None:
        pass


def _apply(sw: st.SimSwitch, lines: list[str]) -> None:
    ctx_port: str | None = None
    ctx_vlan: int | None = None
    for raw in lines:
        line = raw.strip()
        if line == "exit":
            ctx_port = ctx_vlan = None
            continue
        if m := re.fullmatch(r"interface (\S+)", line):
            if m.group(1) not in sw.ports:
                raise DriverError("cli_rejected", f"Invalid input: {m.group(1)}", protocol="ssh")
            ctx_port = m.group(1)
            continue
        if m := re.fullmatch(r"vlan (\d+)", line):
            ctx_vlan = int(m.group(1))
            sw.vlans.setdefault(ctx_vlan, f"VLAN{ctx_vlan}")
            continue
        if m := re.fullmatch(r"no vlan (\d+)", line):
            vid = int(m.group(1))
            if vid in (1, sw.mgmt_vlan):
                raise DriverError("cli_rejected", "Cannot delete this VLAN", protocol="ssh")
            sw.vlans.pop(vid, None)
            continue
        if line == "write memory":
            sw.startup_config = sw.running_config()
            continue
        if ctx_port:
            p = sw.ports[ctx_port]
            if line == "enable":
                p.enabled = True
            elif line == "disable":
                p.enabled = False
            elif m := re.fullmatch(r'name "(.*)"', line):
                p.description = m.group(1)
            elif line == "no name":
                p.description = ""
            elif m := re.fullmatch(r"speed-duplex (\S+)", line):
                p.config_mode = m.group(1)
            elif line == "power-over-ethernet":
                p.poe_enabled = True
            elif line == "no power-over-ethernet":
                p.poe_enabled = False
            elif m := re.fullmatch(r"power-over-ethernet (low|high|critical)", line):
                p.poe_priority = m.group(1)
            elif m := re.fullmatch(r"power-over-ethernet allocate-by (usage|class)", line):
                p.poe_alloc = m.group(1)
            elif m := re.fullmatch(r"power-over-ethernet allocate-by value (\d+)", line):
                p.poe_alloc = "value"
                p.poe_value = int(m.group(1))
            else:
                raise DriverError("cli_rejected", f"Invalid input: {line}", protocol="ssh")
            continue
        if ctx_vlan is not None:
            if m := re.fullmatch(r'name "(.*)"', line):
                sw.vlans[ctx_vlan] = m.group(1)
            elif m := re.fullmatch(r"(no )?(tagged|untagged) (\S+)", line):
                port = m.group(3)
                if m.group(1):
                    if m.group(2) == "untagged" and sw.untagged.get(port) == ctx_vlan:
                        sw.untagged[port] = 1
                    elif ctx_vlan in sw.tagged.get(port, []):
                        sw.tagged[port].remove(ctx_vlan)
                elif m.group(2) == "untagged":
                    sw.untagged[port] = ctx_vlan
                else:
                    sw.tagged.setdefault(port, []).append(ctx_vlan)
            else:
                raise DriverError("cli_rejected", f"Invalid input: {line}", protocol="ssh")
            continue
        # Global-context allow-listed commands are recorded verbatim in the running config.
        if re.match(r"^(timesync|sntp|time timezone|snmpv3|ip authorized-managers|port-security|spanning-tree|"
                    r"no spanning-tree|dhcp-snooping|no dhcp-snooping|radius-server|tacacs-server|ip ssh|"
                    r"no telnet-server|no web-management)", line):
            masked = re.sub(r"(auth \S+ )\S+( priv \S+ )\S+", r"\1********\2********", line)
            masked = re.sub(r"(key )\S+", r"\1********", masked)
            if masked not in sw.extra_config:
                sw.extra_config.append(masked)
            continue
        raise DriverError("cli_rejected", f"Invalid input: {line}", protocol="ssh")
