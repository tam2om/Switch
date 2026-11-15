"""Aruba AOS-Switch (16.11) driver combining REST (configuration), SNMPv3 (monitoring) and SSH (fallback CLI).

Read preference: REST resource if the device answered it during probing, otherwise SNMP.
Write preference: REST resource, otherwise allow-listed CLI over SSH (cli_commands.py).
Every write is followed by a read-back in the change engine (verification is not assumed).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.drivers.aruba.aos_switch import cli_commands as cli
from app.drivers.aruba.aos_switch import configuration, lldp, mac_table, poe, ports, system, vlans
from app.drivers.aruba.aos_switch.capabilities import capabilities_for
from app.drivers.aruba.aos_switch.rest_client import RestClient
from app.drivers.aruba.aos_switch.snmp_client import SnmpClient, SnmpTransport
from app.drivers.aruba.aos_switch.ssh_client import SshSession
from app.drivers.base import (
    ConfigText,
    DriverError,
    HealthInfo,
    LldpNeighbor,
    MacEntry,
    OperationResult,
    PoePortInfo,
    PoeSummary,
    PortCounters,
    PortInfo,
    SwitchDriver,
    SystemInfo,
    UnsupportedOperation,
    VlanInfo,
    VlanMembership,
)

log = logging.getLogger(__name__)

PROBE_RESOURCES = {
    "system.read": "/system/status",
    "ports.read": "/ports",
    "vlans.read": "/vlans",
    "vlan_ports.read": "/vlans-ports",
    "poe.read": "/poe/ports",
    "poe.stats": "/poe/ports/stats",
    "mac.read": "/mac-table",
    "lldp.read": "/lldp/remote-device",
}


@dataclass
class DriverContext:
    host: str
    firmware: str | None = None
    rest_factory: Callable[[], RestClient] | None = None
    snmp_factory: Callable[[], SnmpTransport] | None = None
    ssh_factory: Callable[[], SshSession] | None = None
    # Capability state previously probed on this switch: {"ports.read": True, ...}
    probed: dict = field(default_factory=dict)


class AosSwitchDriver(SwitchDriver):
    name = "aruba_aos_s"

    def __init__(self, ctx: DriverContext):
        self.ctx = ctx
        self.caps = capabilities_for(ctx.firmware)
        self._rest: RestClient | None = None
        self._snmp: SnmpClient | None = None
        self._ssh: SshSession | None = None
        self.errors: list[dict] = []

    # ---- protocol handles ----
    @property
    def rest(self) -> RestClient:
        if self._rest is None:
            if not self.ctx.rest_factory:
                raise DriverError("no_credentials", "REST credentials are not configured", protocol="rest")
            self._rest = self.ctx.rest_factory()
        return self._rest

    @property
    def snmp(self) -> SnmpClient:
        if self._snmp is None:
            if not self.ctx.snmp_factory:
                raise DriverError("no_credentials", "SNMPv3 credentials are not configured", protocol="snmp")
            self._snmp = SnmpClient(self.ctx.snmp_factory())
        return self._snmp

    @property
    def ssh(self) -> SshSession:
        if self._ssh is None:
            if not self.ctx.ssh_factory:
                raise DriverError("no_credentials", "SSH credentials are not configured", protocol="ssh")
            self._ssh = self.ctx.ssh_factory()
        return self._ssh

    def close(self) -> None:
        for handle in (self._rest, self._ssh):
            try:
                if handle is not None:
                    handle.close()
            except Exception:  # noqa: BLE001
                log.debug("close failed", exc_info=True)
        self._rest = self._ssh = None

    def _rest_ok(self, key: str) -> bool:
        if not self.ctx.rest_factory:
            return False
        return self.ctx.probed.get(key, True) is not False

    def _fallback(self, key: str, exc: DriverError) -> None:
        self.errors.append({"capability": key, **exc.to_dict()})
        if exc.code in ("not_found", "unsupported"):
            self.ctx.probed[key] = False

    # ---- probe ----
    def probe(self) -> dict:
        result: dict = {"rest": None, "snmp": None, "ssh": None, "resources": {}, "errors": []}
        if self.ctx.rest_factory:
            try:
                self.rest.login()
                result["rest"] = True
                result["rest_version"] = self.rest.api_version
                for key, path in PROBE_RESOURCES.items():
                    try:
                        self.rest.get(path)
                        result["resources"][key] = True
                    except DriverError as exc:
                        result["resources"][key] = False
                        result["errors"].append({"resource": path, **exc.to_dict()})
            except DriverError as exc:
                result["rest"] = False
                result["errors"].append(exc.to_dict())
        if self.ctx.snmp_factory:
            try:
                self.snmp.get(["1.3.6.1.2.1.1.5.0"])
                result["snmp"] = True
            except DriverError as exc:
                result["snmp"] = False
                result["errors"].append(exc.to_dict())
        if self.ctx.ssh_factory:
            try:
                self.ssh.show("show version")
                result["ssh"] = True
            except DriverError as exc:
                result["ssh"] = False
                result["errors"].append(exc.to_dict())
        self.ctx.probed.update(result["resources"])
        return result

    # ---- reads ----
    def get_system(self) -> SystemInfo:
        info: SystemInfo | None = None
        if self._rest_ok("system.read"):
            try:
                info = system.parse_rest_system(self.rest.get("/system"), self.rest.get("/system/status"))
            except DriverError as exc:
                self._fallback("system.read", exc)
        snmp_info = None
        if self.ctx.snmp_factory:
            try:
                snmp_info = system.snmp_system(self.snmp)
            except DriverError as exc:
                if info is None:
                    raise
                self.errors.append(exc.to_dict())
        if info is None and snmp_info is None:
            raise DriverError("unavailable", "No protocol could read system information")
        if info is None:
            return snmp_info  # type: ignore[return-value]
        if snmp_info:
            info.uptime_seconds = snmp_info.uptime_seconds
            info.sys_object_id = snmp_info.sys_object_id
            info.description = snmp_info.description
            info.product_number = info.product_number or snmp_info.product_number
            info.firmware = info.firmware or snmp_info.firmware
        return info

    def get_health(self, include_temperature: bool = True) -> HealthInfo:
        return system.snmp_health(self.snmp, include_temperature=include_temperature)

    def get_port_status(self) -> list[PortInfo]:
        if self.ctx.snmp_factory:
            return ports.snmp_ports(self.snmp)
        return self.get_ports()

    def get_ports(self) -> list[PortInfo]:
        rest_ports = None
        if self._rest_ok("ports.read"):
            try:
                rest_ports = ports.parse_rest_ports(self.rest.get("/ports"))
            except DriverError as exc:
                self._fallback("ports.read", exc)
        snmp_ports = None
        if self.ctx.snmp_factory:
            try:
                snmp_ports = ports.snmp_ports(self.snmp)
            except DriverError as exc:
                if rest_ports is None:
                    raise
                self.errors.append(exc.to_dict())
        if rest_ports is None and snmp_ports is None:
            raise DriverError("unavailable", "No protocol could read port information")
        return ports.merge_ports(rest_ports, snmp_ports)

    def get_port_config_modes(self, names: list[str] | None = None) -> dict[str, str]:
        """REST /ports when available; otherwise the running-config (REST CLI or SSH), because IF-MIB does not
        carry the configured speed-duplex mode. With the running-config, a named port that has no interface block
        is at the default ('auto'), since AOS-Switch only writes non-default settings."""
        if self._rest_ok("ports.read"):
            try:
                return {p.name: p.config_mode for p in ports.parse_rest_ports(self.rest.get("/ports")) if p.config_mode}
            except DriverError as exc:
                self._fallback("ports.read", exc)
        modes = configuration.port_speed_modes(self.get_running_config().text)
        for name in names or []:
            modes.setdefault(cli.port(name), "auto")
        return modes

    def get_port_counters(self) -> list[PortCounters]:
        return ports.snmp_counters(self.snmp)

    def get_vlans(self) -> list[VlanInfo]:
        if self._rest_ok("vlans.read"):
            try:
                return vlans.parse_rest_vlans(self.rest.get("/vlans"))
            except DriverError as exc:
                self._fallback("vlans.read", exc)
        return vlans.snmp_vlans(self.snmp)

    def get_vlan_memberships(self) -> list[VlanMembership]:
        if self._rest_ok("vlan_ports.read"):
            try:
                return vlans.parse_rest_vlan_ports(self.rest.get("/vlans-ports"))
            except DriverError as exc:
                self._fallback("vlan_ports.read", exc)
        if not self.ctx.snmp_factory:
            raise UnsupportedOperation("VLAN port membership needs REST /vlans-ports or SNMPv3 (Q-BRIDGE-MIB)",
                                       protocol="rest")
        members = vlans.snmp_vlan_memberships(self.snmp)
        if not members:
            raise UnsupportedOperation("The device returned no Q-BRIDGE-MIB VLAN port membership", protocol="snmp")
        return members

    def get_poe_ports(self) -> list[PoePortInfo]:
        if self._rest_ok("poe.read"):
            try:
                stats = None
                if self._rest_ok("poe.stats"):
                    try:
                        stats = self.rest.get("/poe/ports/stats")
                    except DriverError as exc:
                        self._fallback("poe.stats", exc)
                return poe.parse_rest_poe(self.rest.get("/poe/ports"), stats)
            except DriverError as exc:
                self._fallback("poe.read", exc)
        if not self.ctx.snmp_factory:
            raise UnsupportedOperation("Per-port PoE needs REST /poe/ports or SNMPv3 (POWER-ETHERNET-MIB)",
                                       protocol="rest")
        return poe.snmp_poe_ports(self.snmp)

    def get_poe_summary(self) -> PoeSummary:
        return poe.snmp_poe_summary(self.snmp)

    def get_mac_table(self) -> list[MacEntry]:
        if self._rest_ok("mac.read"):
            try:
                return mac_table.parse_rest_mac_table(self.rest.get("/mac-table"))
            except DriverError as exc:
                self._fallback("mac.read", exc)
        return mac_table.snmp_mac_table(self.snmp)

    def get_lldp_neighbors(self) -> list[LldpNeighbor]:
        if self._rest_ok("lldp.read"):
            try:
                return lldp.parse_rest_lldp(self.rest.get("/lldp/remote-device"))
            except DriverError as exc:
                self._fallback("lldp.read", exc)
        return lldp.snmp_lldp(self.snmp)

    def get_running_config(self) -> ConfigText:
        if self.ctx.rest_factory and self.ctx.probed.get("config.running", True) is not False:
            try:
                text = self.rest.cli("show running-config")
                if configuration.looks_like_config(text):
                    return ConfigText(text=configuration.normalize_config(text), source="rest-cli")
            except DriverError as exc:
                self._fallback("config.running", exc)
        text = self.ssh.show("show running-config")
        if not configuration.looks_like_config(text):
            raise DriverError("invalid_config", "Retrieved text does not look like a switch configuration",
                              protocol="ssh")
        return ConfigText(text=configuration.normalize_config(text), source="ssh")

    def get_startup_config(self) -> ConfigText:
        text = self.ssh.show("show config")
        return ConfigText(text=configuration.normalize_config(text), source="ssh", kind="startup")

    # ---- writes ----
    def _ssh_config(self, lines: list[str], what: str) -> OperationResult:
        self.ssh.configure(lines)
        return OperationResult(ok=True, protocol="ssh", message=what, details={"commands": len(lines)})

    def _put_port(self, port: str, body: dict, what: str, cli_lines: list[str]) -> OperationResult:
        cli.port(port)
        if self._rest_ok("ports.read"):
            try:
                self.rest.put(f"/ports/{port}", {"id": port, **body})
                return OperationResult(ok=True, protocol="rest", message=what)
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("ports.write", exc)
        return self._ssh_config(cli_lines, what)

    def set_port_admin(self, port: str, enabled: bool) -> OperationResult:
        return self._put_port(port, {"is_port_enabled": enabled}, f"port {port} {'enabled' if enabled else 'disabled'}",
                              cli.cmd_port_admin(port, enabled))

    def set_port_description(self, port: str, description: str) -> OperationResult:
        cli.description(description)
        return self._put_port(port, {"name": description}, f"port {port} description updated",
                              cli.cmd_port_description(port, description))

    def set_port_speed_duplex(self, port: str, mode: str) -> OperationResult:
        if mode not in ports.CONFIG_MODES_REV:
            raise DriverError("invalid_parameter", f"Unsupported speed/duplex mode {mode!r}")
        return self._put_port(port, {"config_mode": ports.CONFIG_MODES_REV[mode]}, f"port {port} speed-duplex {mode}",
                              cli.cmd_port_speed(port, mode))

    def create_vlan(self, vlan_id: int, name: str) -> OperationResult:
        cli.vlan_id(vlan_id)
        cli.vlan_name(name)
        if self._rest_ok("vlans.read"):
            try:
                self.rest.post("/vlans", {"vlan_id": vlan_id, "name": name})
                return OperationResult(ok=True, protocol="rest", message=f"VLAN {vlan_id} created")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("vlans.write", exc)
        return self._ssh_config(cli.cmd_vlan_create(vlan_id, name), f"VLAN {vlan_id} created")

    def rename_vlan(self, vlan_id: int, name: str) -> OperationResult:
        cli.vlan_id(vlan_id)
        cli.vlan_name(name)
        if self._rest_ok("vlans.read"):
            try:
                self.rest.put(f"/vlans/{vlan_id}", {"vlan_id": vlan_id, "name": name})
                return OperationResult(ok=True, protocol="rest", message=f"VLAN {vlan_id} renamed")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("vlans.write", exc)
        return self._ssh_config(cli.cmd_vlan_create(vlan_id, name), f"VLAN {vlan_id} renamed")

    def delete_vlan(self, vlan_id: int) -> OperationResult:
        lines = cli.cmd_vlan_delete(vlan_id)
        if self._rest_ok("vlans.read"):
            try:
                self.rest.delete(f"/vlans/{vlan_id}")
                return OperationResult(ok=True, protocol="rest", message=f"VLAN {vlan_id} deleted")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("vlans.write", exc)
        return self._ssh_config(lines, f"VLAN {vlan_id} deleted")

    def set_port_vlan(self, port: str, vlan_id: int, mode: str) -> OperationResult:
        lines = cli.cmd_port_vlan(port, vlan_id, mode)
        if self._rest_ok("vlan_ports.read"):
            try:
                self.rest.post("/vlans-ports", {"vlan_id": vlan_id, "port_id": port,
                                                "port_mode": vlans.PORT_MODES_REV[mode]})
                return OperationResult(ok=True, protocol="rest", message=f"port {port} {mode} VLAN {vlan_id}")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("vlan_ports.write", exc)
        return self._ssh_config(lines, f"port {port} {mode} VLAN {vlan_id}")

    def remove_port_vlan(self, port: str, vlan_id: int) -> OperationResult:
        cli.port(port)
        cli.vlan_id(vlan_id)
        if self._rest_ok("vlan_ports.read"):
            try:
                self.rest.delete(f"/vlans-ports/{vlan_id}-{port}")
                return OperationResult(ok=True, protocol="rest", message=f"port {port} removed from VLAN {vlan_id}")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("vlan_ports.write", exc)
        return self._ssh_config(cli.cmd_port_vlan_remove(port, vlan_id, "tagged"),
                                f"port {port} removed from VLAN {vlan_id}")

    def set_poe(self, port: str, *, enabled: bool | None = None, priority: str | None = None,
                allocation_method: str | None = None, allocated_power_w: float | None = None) -> OperationResult:
        lines = cli.cmd_poe(port, enabled, priority, allocation_method, allocated_power_w)
        if self._rest_ok("poe.read"):
            body: dict = {"port_id": port}
            if enabled is not None:
                body["is_poe_enabled"] = enabled
            if priority is not None:
                body["poe_priority"] = poe.PRIORITY_REV[priority]
            if allocation_method is not None:
                body["poe_allocation_method"] = poe.ALLOC_REV[allocation_method]
                if allocation_method == "value" and allocated_power_w is not None:
                    body["allocated_power_in_watts"] = int(allocated_power_w)
            try:
                self.rest.put(f"/ports/{port}/poe", body)
                return OperationResult(ok=True, protocol="rest", message=f"PoE updated on port {port}")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("poe.write", exc)
        return self._ssh_config(lines, f"PoE updated on port {port}")

    def restart_poe(self, port: str) -> OperationResult:
        off, on = cli.cmd_poe_restart(port)
        if self._rest_ok("poe.read"):
            try:
                self.rest.put(f"/ports/{port}/poe", {"port_id": port, "is_poe_enabled": False})
                self.rest.put(f"/ports/{port}/poe", {"port_id": port, "is_poe_enabled": True})
                return OperationResult(ok=True, protocol="rest", message=f"PoE restarted on port {port}")
            except DriverError as exc:
                if exc.code not in ("not_found", "unsupported"):
                    raise
                self._fallback("poe.write", exc)
        self.ssh.configure(off)
        self.ssh.configure(on)
        return OperationResult(ok=True, protocol="ssh", message=f"PoE restarted on port {port}")

    def apply_cli(self, commands: list[str]) -> OperationResult:
        for c in commands:
            cli.assert_safe_line(c)
        return self._ssh_config(commands, f"{len(commands)} configuration lines applied")

    def upload_startup_config(self, text: str) -> OperationResult:
        if not configuration.looks_like_config(text):
            raise DriverError("invalid_config", "Refusing to upload text that is not a switch configuration")
        self.ssh.put_file("/cfg/startup-config", text)
        return OperationResult(ok=True, protocol="ssh", message="startup-config uploaded (active after reload)")

    def write_memory(self) -> OperationResult:
        if self.ctx.rest_factory:
            try:
                self.rest.cli("write memory")
                return OperationResult(ok=True, protocol="rest-cli", message="configuration saved")
            except DriverError as exc:
                self._fallback("config.write_memory", exc)
        self.ssh.configure(["write memory"])
        return OperationResult(ok=True, protocol="ssh", message="configuration saved")
