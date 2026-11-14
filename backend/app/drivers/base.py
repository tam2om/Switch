"""Hardware driver abstraction.

Drivers return plain dataclasses so the rest of the application never depends on a vendor's wire format.
Every method either returns real device data or raises DriverError; drivers never invent values. Fields a
device did not report are None.
"""

from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


class DriverError(Exception):
    """Structured device error."""

    def __init__(self, code: str, message: str, *, protocol: str = "", retriable: bool = False,
                 details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.protocol = protocol
        self.retriable = retriable
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "protocol": self.protocol, "retriable": self.retriable,
                "details": self.details}


class UnsupportedOperation(DriverError):
    def __init__(self, message: str, **kw: Any):
        super().__init__("unsupported", message, **kw)


@dataclass
class SystemInfo:
    hostname: str | None = None
    product_number: str | None = None  # e.g. JL356A
    model_name: str | None = None
    serial_number: str | None = None
    base_mac: str | None = None
    firmware: str | None = None
    rom_version: str | None = None
    uptime_seconds: int | None = None
    location: str | None = None
    contact: str | None = None
    sys_object_id: str | None = None
    description: str | None = None


@dataclass
class HealthInfo:
    cpu_pct: float | None = None
    mem_pct: float | None = None
    mem_total_bytes: int | None = None
    mem_free_bytes: int | None = None
    temperature_c: float | None = None
    uptime_seconds: int | None = None


@dataclass
class PortInfo:
    name: str
    if_index: int | None = None
    description: str = ""
    admin_up: bool | None = None
    oper_up: bool | None = None
    speed_mbps: int | None = None
    duplex: str | None = None  # full | half
    config_mode: str | None = None  # auto | 10-half | 10-full | 100-half | 100-full | 1000-full | auto-10-100 ...
    port_type: str = ""
    trunk_group: str | None = None


@dataclass
class PortCounters:
    if_index: int
    name: str | None = None
    in_octets: int | None = None
    out_octets: int | None = None
    in_errors: int | None = None
    out_errors: int | None = None
    in_discards: int | None = None
    out_discards: int | None = None
    oper_up: bool | None = None
    speed_mbps: int | None = None


@dataclass
class VlanInfo:
    vlan_id: int
    name: str = ""
    status: str = "port_based"
    is_management: bool = False
    is_voice: bool = False


@dataclass
class VlanMembership:
    vlan_id: int
    port: str
    mode: Literal["tagged", "untagged", "forbidden"]


@dataclass
class PoePortInfo:
    port: str
    enabled: bool | None = None
    priority: str | None = None  # low | high | critical
    allocation_method: str | None = None  # usage | class | value
    allocated_power_w: float | None = None
    power_drawn_w: float | None = None
    detection_status: str | None = None  # delivering | searching | disabled | fault | other
    power_class: str | None = None
    fault: str | None = None


@dataclass
class PoeSummary:
    budget_w: float | None = None
    consumed_w: float | None = None
    oper_status: str | None = None


@dataclass
class MacEntry:
    mac: str
    vlan_id: int
    port: str


@dataclass
class LldpNeighbor:
    local_port: str
    chassis_id: str = ""
    remote_port: str = ""
    remote_port_desc: str = ""
    system_name: str = ""
    system_description: str = ""
    mgmt_address: str | None = None
    capabilities: list[str] = field(default_factory=list)


@dataclass
class ConfigText:
    text: str
    source: str  # rest-cli | ssh | simulator
    kind: Literal["running", "startup"] = "running"


@dataclass
class OperationResult:
    ok: bool
    protocol: str
    message: str = ""
    details: dict = field(default_factory=dict)


def to_dict(obj: Any) -> Any:
    if isinstance(obj, list):
        return [to_dict(o) for o in obj]
    return asdict(obj)


class SwitchDriver(abc.ABC):
    """Interface every device driver implements. Write operations must return only after the change was applied;
    verification is performed separately by the change engine by re-reading device state."""

    name: str = "base"
    is_simulated: bool = False

    # ---- lifecycle ----
    def close(self) -> None:  # noqa: B027 - optional hook
        pass

    def __enter__(self) -> SwitchDriver:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- discovery / capabilities ----
    @abc.abstractmethod
    def probe(self) -> dict:
        """Check reachability of each protocol and which resources work. Returns the capability map."""

    # ---- reads ----
    @abc.abstractmethod
    def get_system(self) -> SystemInfo: ...

    @abc.abstractmethod
    def get_health(self) -> HealthInfo: ...

    @abc.abstractmethod
    def get_ports(self) -> list[PortInfo]: ...

    @abc.abstractmethod
    def get_port_counters(self) -> list[PortCounters]: ...

    @abc.abstractmethod
    def get_vlans(self) -> list[VlanInfo]: ...

    @abc.abstractmethod
    def get_vlan_memberships(self) -> list[VlanMembership]: ...

    @abc.abstractmethod
    def get_poe_ports(self) -> list[PoePortInfo]: ...

    @abc.abstractmethod
    def get_poe_summary(self) -> PoeSummary: ...

    @abc.abstractmethod
    def get_mac_table(self) -> list[MacEntry]: ...

    @abc.abstractmethod
    def get_lldp_neighbors(self) -> list[LldpNeighbor]: ...

    @abc.abstractmethod
    def get_running_config(self) -> ConfigText: ...

    def get_startup_config(self) -> ConfigText:
        raise UnsupportedOperation("Reading startup-config is not supported by this driver")

    # ---- writes ----
    @abc.abstractmethod
    def set_port_admin(self, port: str, enabled: bool) -> OperationResult: ...

    @abc.abstractmethod
    def set_port_description(self, port: str, description: str) -> OperationResult: ...

    @abc.abstractmethod
    def set_port_speed_duplex(self, port: str, mode: str) -> OperationResult: ...

    @abc.abstractmethod
    def create_vlan(self, vlan_id: int, name: str) -> OperationResult: ...

    @abc.abstractmethod
    def rename_vlan(self, vlan_id: int, name: str) -> OperationResult: ...

    @abc.abstractmethod
    def delete_vlan(self, vlan_id: int) -> OperationResult: ...

    @abc.abstractmethod
    def set_port_vlan(self, port: str, vlan_id: int, mode: str) -> OperationResult:
        """mode: tagged | untagged"""

    @abc.abstractmethod
    def remove_port_vlan(self, port: str, vlan_id: int) -> OperationResult: ...

    @abc.abstractmethod
    def set_poe(self, port: str, *, enabled: bool | None = None, priority: str | None = None,
                allocation_method: str | None = None, allocated_power_w: float | None = None) -> OperationResult: ...

    @abc.abstractmethod
    def restart_poe(self, port: str) -> OperationResult: ...

    @abc.abstractmethod
    def apply_cli(self, commands: list[str]) -> OperationResult:
        """Apply validated configuration-mode commands (already allow-listed by the caller)."""

    @abc.abstractmethod
    def upload_startup_config(self, text: str) -> OperationResult: ...

    @abc.abstractmethod
    def write_memory(self) -> OperationResult: ...
