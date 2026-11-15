"""Registered configuration operations.

Each operation defines: parameter validation, the permission it needs, a per-switch risk assessment based on
the stored inventory (uplinks, management VLAN, current memberships), a live pre-check against the device,
execution through the driver, and verification by reading the device state back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import P
from app.drivers.aruba.aos_switch import cli_commands as cli
from app.drivers.base import DriverError, OperationResult, SwitchDriver
from app.models import ConfigBackup, Switch, SwitchNeighbor, SwitchPort

RISK_ORDER = ["low", "medium", "high", "critical"]


def max_risk(*risks: str) -> str:
    return max(risks, key=RISK_ORDER.index) if risks else "low"


class PrecheckFailed(Exception):
    pass


@dataclass
class Risk:
    level: str = "low"
    reasons: list[str] = field(default_factory=list)

    def bump(self, level: str, reason: str) -> None:
        self.level = max_risk(self.level, level)
        self.reasons.append(reason)


def uplink_ports(db: Session, sw: Switch) -> set[str]:
    """Configured uplinks plus ports where LLDP sees another switch/bridge, plus trunk members."""
    ups = set(sw.uplink_ports or [])
    for n in db.execute(select(SwitchNeighbor).where(SwitchNeighbor.switch_id == sw.id)).scalars():
        desc = (n.system_description or "").lower()
        if n.remote_switch_id is not None or "switch" in desc:
            ups.add(n.local_port)
    for p in db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id, SwitchPort.trunk_group.is_not(None))).scalars():
        ups.add(p.name)
    return ups


def _port_row(db: Session, sw: Switch, port: str) -> SwitchPort | None:
    return db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id, SwitchPort.name == port)).scalar_one_or_none()


class Operation:
    name: ClassVar[str]
    title: ClassVar[str]
    permission: ClassVar[P]
    Params: ClassVar[type[BaseModel]]
    takes_backup: ClassVar[bool] = True
    saves_config: ClassVar[bool] = True
    refresh: ClassVar[str] = "inventory"  # polling category to refresh after success
    warning: ClassVar[str] = ""

    def parse(self, params: dict) -> BaseModel:
        try:
            return self.Params(**params)
        except ValidationError as exc:
            from app.core.errors import bad_request

            raise bad_request("Invalid operation parameters", "invalid_params",
                              {"errors": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}) from exc

    def describe(self, p: Any) -> str:
        return self.title

    def assess(self, db: Session, sw: Switch, p: Any) -> Risk:
        return Risk()

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: Any) -> None:  # noqa: B027
        pass

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: Any) -> list[OperationResult]:
        raise NotImplementedError

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: Any) -> tuple[bool, dict]:
        raise NotImplementedError


# ------------------------------------------------------------------ parameter models

PortName = str


def _ports(v: list[str]) -> list[str]:
    for p in v:
        cli.port(p)
    if len(set(v)) != len(v):
        raise ValueError("duplicate ports")
    return v


class PortAdminParams(BaseModel):
    ports: list[PortName] = Field(min_length=1, max_length=52)
    enabled: bool
    _v = field_validator("ports")(_ports)


class PortDescItem(BaseModel):
    port: PortName
    description: str = Field(max_length=64)

    @field_validator("port")
    @classmethod
    def _p(cls, v: str) -> str:
        return cli.port(v)

    @field_validator("description")
    @classmethod
    def _d(cls, v: str) -> str:
        return cli.description(v)


class PortDescriptionParams(BaseModel):
    items: list[PortDescItem] = Field(min_length=1, max_length=52)


class PortSpeedParams(BaseModel):
    port: PortName
    mode: str = Field(json_schema_extra={"enum": sorted(cli.SPEED_MODES)})

    @field_validator("port")
    @classmethod
    def _p(cls, v: str) -> str:
        return cli.port(v)

    @field_validator("mode")
    @classmethod
    def _m(cls, v: str) -> str:
        if v not in cli.SPEED_MODES:
            raise ValueError(f"mode must be one of {sorted(cli.SPEED_MODES)}")
        return v


class PortVlanParams(BaseModel):
    ports: list[PortName] = Field(min_length=1, max_length=52)
    untagged_vlan: int | None = Field(default=None, ge=1, le=4094)
    add_tagged: list[int] = Field(default_factory=list)
    remove_tagged: list[int] = Field(default_factory=list)
    _v = field_validator("ports")(_ports)

    @field_validator("add_tagged", "remove_tagged")
    @classmethod
    def _vl(cls, v: list[int]) -> list[int]:
        for x in v:
            cli.vlan_id(x)
        return sorted(set(v))

    @model_validator(mode="after")
    def _any(self) -> PortVlanParams:
        if self.untagged_vlan is None and not self.add_tagged and not self.remove_tagged:
            raise ValueError("Specify an untagged VLAN or tagged VLANs to add/remove")
        if set(self.add_tagged) & set(self.remove_tagged):
            raise ValueError("A VLAN cannot be both added and removed")
        if self.untagged_vlan is not None and self.untagged_vlan in self.add_tagged:
            raise ValueError("A VLAN cannot be both untagged and tagged on the same port")
        return self


class VlanCreateParams(BaseModel):
    vlan_id: int = Field(ge=2, le=4094)
    name: str

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return cli.vlan_name(v)


class VlanDeleteParams(BaseModel):
    vlan_id: int = Field(ge=2, le=4094)


class PoeParams(BaseModel):
    ports: list[PortName] = Field(min_length=1, max_length=48)
    enabled: bool | None = None
    priority: str | None = Field(default=None, json_schema_extra={"enum": sorted(cli.POE_PRIORITIES)})
    allocation_method: str | None = Field(default=None, json_schema_extra={"enum": sorted(cli.POE_ALLOC)})
    allocated_power_w: float | None = Field(default=None, ge=1, le=30)
    _v = field_validator("ports")(_ports)

    @model_validator(mode="after")
    def _check(self) -> PoeParams:
        if self.enabled is None and self.priority is None and self.allocation_method is None:
            raise ValueError("Nothing to change")
        if self.priority is not None and self.priority not in cli.POE_PRIORITIES:
            raise ValueError("priority must be low, high or critical")
        if self.allocation_method is not None and self.allocation_method not in cli.POE_ALLOC:
            raise ValueError("allocation_method must be usage, class or value")
        if self.allocation_method == "value" and self.allocated_power_w is None:
            raise ValueError("allocated_power_w is required for allocation by value")
        return self


class PoeRestartParams(BaseModel):
    port: PortName

    @field_validator("port")
    @classmethod
    def _p(cls, v: str) -> str:
        return cli.port(v)


class SntpParams(BaseModel):
    servers: list[str] = Field(min_length=1, max_length=3)
    timezone_minutes: int | None = Field(default=None, ge=-720, le=840)

    @model_validator(mode="after")
    def _c(self) -> SntpParams:
        cli.cmd_sntp(self.servers, self.timezone_minutes)
        return self


class SnmpUserParams(BaseModel):
    username: str
    auth_password: str = Field(json_schema_extra={"format": "password", "writeOnly": True})
    priv_password: str = Field(json_schema_extra={"format": "password", "writeOnly": True})
    access: Literal["ro", "rw"] = "ro"

    @model_validator(mode="after")
    def _c(self) -> SnmpUserParams:
        cli.cmd_snmpv3_user(self.username, "sha", self.auth_password, "aes", self.priv_password, self.access)
        return self


class AuthorizedManagerParams(BaseModel):
    network: str
    mask: str
    access: Literal["manager", "operator"] = "manager"

    @model_validator(mode="after")
    def _c(self) -> AuthorizedManagerParams:
        cli.cmd_ip_authorized_manager(self.network, self.mask, self.access)
        return self


class PortSecurityParams(BaseModel):
    ports: list[PortName] = Field(min_length=1, max_length=48)
    learn_mode: Literal["continuous", "static", "configured", "port-access", "limited-continuous"] = "continuous"
    address_limit: int = Field(default=1, ge=1, le=64)
    action: Literal["none", "send-alarm", "send-disable"] = "send-alarm"
    _v = field_validator("ports")(_ports)

    @model_validator(mode="after")
    def _c(self) -> PortSecurityParams:
        for p in self.ports:
            cli.cmd_port_security(p, self.learn_mode, self.address_limit, self.action)
        return self


class StpParams(BaseModel):
    ports: list[PortName] = Field(min_length=1, max_length=48)
    bpdu_protection: bool = True
    admin_edge: bool = True
    _v = field_validator("ports")(_ports)


class DhcpSnoopingParams(BaseModel):
    enabled: bool
    vlans: list[int] = Field(default_factory=list)
    trusted_ports: list[PortName] = Field(default_factory=list)

    @model_validator(mode="after")
    def _c(self) -> DhcpSnoopingParams:
        if self.enabled and not self.vlans:
            raise ValueError("Select at least one VLAN")
        if self.enabled and not self.trusted_ports:
            raise ValueError("At least one trusted (uplink) port is required, otherwise DHCP stops working")
        cli.cmd_dhcp_snooping(self.enabled, self.vlans, self.trusted_ports)
        return self


class AaaServerParams(BaseModel):
    protocol: Literal["radius", "tacacs"]
    host: str
    key: str = Field(json_schema_extra={"format": "password", "writeOnly": True})

    @model_validator(mode="after")
    def _c(self) -> AaaServerParams:
        if self.protocol == "radius":
            cli.cmd_radius_server(self.host, self.key)
        elif self.protocol == "tacacs":
            cli.cmd_tacacs_server(self.host, self.key)
        else:
            raise ValueError("protocol must be radius or tacacs")
        return self


class EmptyParams(BaseModel):
    note: str = Field(default="", max_length=255)


class RestoreParams(BaseModel):
    backup_id: int


# ------------------------------------------------------------------ operations

class PortAdmin(Operation):
    name = "port_admin"
    title = "Enable/disable ports"
    permission = P.PORT_MANAGE
    Params = PortAdminParams
    refresh = "availability"

    def describe(self, p: PortAdminParams) -> str:
        return f"{'Enable' if p.enabled else 'Disable'} port(s) {', '.join(p.ports)}"

    def assess(self, db: Session, sw: Switch, p: PortAdminParams) -> Risk:
        r = Risk()
        if p.enabled:
            return r
        r.bump("medium", "Disabling a port disconnects the attached device")
        ups = uplink_ports(db, sw) & set(p.ports)
        if ups:
            r.bump("critical", f"Port(s) {', '.join(sorted(ups))} are uplinks; disabling may isolate the switch")
        if len(p.ports) > 4:
            r.bump("high", f"Bulk port shutdown ({len(p.ports)} ports)")
        for port in p.ports:
            row = _port_row(db, sw, port)
            if row and sw.mgmt_vlan and (row.untagged_vlan == sw.mgmt_vlan or sw.mgmt_vlan in (row.tagged_vlans or [])):
                r.bump("high", f"Port {port} carries the management VLAN {sw.mgmt_vlan}")
        return r

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortAdminParams) -> None:
        names = {x.name for x in drv.get_ports()}
        missing = [x for x in p.ports if x not in names]
        if missing:
            raise PrecheckFailed(f"Port(s) not present on device: {', '.join(missing)}")

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortAdminParams) -> list[OperationResult]:
        return [drv.set_port_admin(x, p.enabled) for x in p.ports]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortAdminParams) -> tuple[bool, dict]:
        state = {x.name: x.admin_up for x in drv.get_ports()}
        wrong = {x: state.get(x) for x in p.ports if state.get(x) is not p.enabled}
        return not wrong, {"mismatch": wrong}


class PortDescription(Operation):
    name = "port_description"
    title = "Change port descriptions"
    permission = P.PORT_MANAGE
    Params = PortDescriptionParams

    def describe(self, p: PortDescriptionParams) -> str:
        return f"Set description on {len(p.items)} port(s)"

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortDescriptionParams) -> list[OperationResult]:
        return [drv.set_port_description(i.port, i.description) for i in p.items]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortDescriptionParams) -> tuple[bool, dict]:
        state = {x.name: x.description for x in drv.get_ports()}
        wrong = {i.port: state.get(i.port) for i in p.items if state.get(i.port) != i.description}
        return not wrong, {"mismatch": wrong}


class PortSpeed(Operation):
    name = "port_speed"
    title = "Change port speed/duplex"
    permission = P.PORT_MANAGE
    Params = PortSpeedParams
    warning = "Changing speed/duplex renegotiates the link and briefly interrupts traffic."

    def describe(self, p: PortSpeedParams) -> str:
        return f"Set port {p.port} speed-duplex to {p.mode}"

    def assess(self, db: Session, sw: Switch, p: PortSpeedParams) -> Risk:
        r = Risk("medium", ["Link renegotiation interrupts traffic on the port"])
        if p.port in uplink_ports(db, sw):
            r.bump("high", f"Port {p.port} is an uplink")
        row = _port_row(db, sw, p.port)
        if row and row.port_type == "SFP+" and p.mode not in ("auto",):
            r.bump("high", "SFP+ ports normally require auto")
        return r

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortSpeedParams) -> list[OperationResult]:
        return [drv.set_port_speed_duplex(p.port, p.mode)]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortSpeedParams) -> tuple[bool, dict]:
        state = {x.name: x.config_mode for x in drv.get_ports()}
        return state.get(p.port) == p.mode, {"actual": state.get(p.port)}


class PortVlan(Operation):
    name = "port_vlan"
    title = "Change port VLAN membership"
    permission = P.VLAN_MANAGE
    Params = PortVlanParams

    def describe(self, p: PortVlanParams) -> str:
        parts = []
        if p.untagged_vlan:
            parts.append(f"untagged VLAN {p.untagged_vlan}")
        if p.add_tagged:
            parts.append(f"tag {p.add_tagged}")
        if p.remove_tagged:
            parts.append(f"untag {p.remove_tagged}")
        return f"Port(s) {', '.join(p.ports)}: " + "; ".join(parts)

    def assess(self, db: Session, sw: Switch, p: PortVlanParams) -> Risk:
        r = Risk("low", [])
        ups = uplink_ports(db, sw) & set(p.ports)
        if ups:
            r.bump("high", f"Changes VLANs on uplink port(s) {', '.join(sorted(ups))}")
        mv = sw.mgmt_vlan
        if mv and (p.untagged_vlan == mv or mv in p.add_tagged or mv in p.remove_tagged):
            r.bump("high", f"Involves the management VLAN {mv}")
        for port in p.ports:
            row = _port_row(db, sw, port)
            if row and mv and p.untagged_vlan and row.untagged_vlan == mv and p.untagged_vlan != mv:
                r.bump("critical", f"Port {port} is untagged in the management VLAN; changing it may cut management access")
            if row and mv in p.remove_tagged and mv in (row.tagged_vlans or []) and port in ups:
                r.bump("critical", f"Removing management VLAN from uplink {port} will isolate the switch")
        if len(p.ports) > 8:
            r.bump("medium", f"{len(p.ports)} ports affected")
        return r

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortVlanParams) -> None:
        vids = {v.vlan_id for v in drv.get_vlans()}
        needed = set(p.add_tagged) | ({p.untagged_vlan} if p.untagged_vlan else set())
        missing = needed - vids
        if missing:
            raise PrecheckFailed(f"VLAN(s) {sorted(missing)} do not exist on the switch; create them first")

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortVlanParams) -> list[OperationResult]:
        out = []
        for port in p.ports:
            if p.untagged_vlan:
                out.append(drv.set_port_vlan(port, p.untagged_vlan, "untagged"))
            for v in p.add_tagged:
                out.append(drv.set_port_vlan(port, v, "tagged"))
            for v in p.remove_tagged:
                try:
                    out.append(drv.remove_port_vlan(port, v))
                except DriverError as exc:
                    if exc.code != "not_found":
                        raise
                    out.append(OperationResult(ok=True, protocol=exc.protocol, message=f"port {port} not in VLAN {v}"))
        return out

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: PortVlanParams) -> tuple[bool, dict]:
        mem = drv.get_vlan_memberships()
        problems = []
        for port in p.ports:
            un = {m.vlan_id for m in mem if m.port == port and m.mode == "untagged"}
            tg = {m.vlan_id for m in mem if m.port == port and m.mode == "tagged"}
            if p.untagged_vlan and p.untagged_vlan not in un:
                problems.append(f"{port}: untagged {sorted(un)}")
            if set(p.add_tagged) - tg:
                problems.append(f"{port}: missing tagged {sorted(set(p.add_tagged) - tg)}")
            if set(p.remove_tagged) & tg:
                problems.append(f"{port}: still tagged {sorted(set(p.remove_tagged) & tg)}")
        return not problems, {"problems": problems}


class VlanCreate(Operation):
    name = "vlan_create"
    title = "Create or rename VLAN"
    permission = P.VLAN_MANAGE
    Params = VlanCreateParams

    def describe(self, p: VlanCreateParams) -> str:
        return f"Create/rename VLAN {p.vlan_id} '{p.name}'"

    def assess(self, db: Session, sw: Switch, p: VlanCreateParams) -> Risk:
        if sw.mgmt_vlan == p.vlan_id:
            return Risk("medium", ["Renames the management VLAN"])
        return Risk()

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: VlanCreateParams) -> list[OperationResult]:
        existing = {v.vlan_id for v in drv.get_vlans()}
        if p.vlan_id in existing:
            return [drv.rename_vlan(p.vlan_id, p.name)]
        return [drv.create_vlan(p.vlan_id, p.name)]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: VlanCreateParams) -> tuple[bool, dict]:
        v = {x.vlan_id: x.name for x in drv.get_vlans()}
        return v.get(p.vlan_id) == p.name, {"actual": v.get(p.vlan_id)}


class VlanDelete(Operation):
    name = "vlan_delete"
    title = "Delete VLAN"
    permission = P.VLAN_MANAGE
    Params = VlanDeleteParams
    warning = "Ports that are untagged members of the VLAN move to the default VLAN 1."

    def describe(self, p: VlanDeleteParams) -> str:
        return f"Delete VLAN {p.vlan_id}"

    def assess(self, db: Session, sw: Switch, p: VlanDeleteParams) -> Risk:
        r = Risk("high", ["VLAN deletion removes all port memberships"])
        if sw.mgmt_vlan == p.vlan_id:
            r.bump("critical", "This is the management VLAN")
        return r

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: VlanDeleteParams) -> None:
        vlans = {v.vlan_id: v for v in drv.get_vlans()}
        if p.vlan_id not in vlans:
            raise PrecheckFailed(f"VLAN {p.vlan_id} does not exist on this switch")
        if vlans[p.vlan_id].is_management or sw.mgmt_vlan == p.vlan_id:
            raise PrecheckFailed("Refusing to delete the management VLAN")

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: VlanDeleteParams) -> list[OperationResult]:
        return [drv.delete_vlan(p.vlan_id)]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: VlanDeleteParams) -> tuple[bool, dict]:
        return p.vlan_id not in {v.vlan_id for v in drv.get_vlans()}, {}


class PoeConfig(Operation):
    name = "poe_config"
    title = "Configure PoE"
    permission = P.POE_MANAGE
    Params = PoeParams
    refresh = "poe"

    def describe(self, p: PoeParams) -> str:
        bits = []
        if p.enabled is not None:
            bits.append("enable" if p.enabled else "disable")
        if p.priority:
            bits.append(f"priority {p.priority}")
        if p.allocation_method:
            bits.append(f"allocate by {p.allocation_method}")
        return f"PoE {', '.join(bits)} on port(s) {', '.join(p.ports)}"

    def assess(self, db: Session, sw: Switch, p: PoeParams) -> Risk:
        r = Risk()
        if p.enabled is False:
            r.bump("medium", "Disabling PoE powers off attached devices (phones, APs, cameras)")
            if len(p.ports) > 8:
                r.bump("high", f"PoE disabled on {len(p.ports)} ports")
        if p.allocation_method == "value":
            r.bump("medium", "A fixed allocation below the device's need can power it off")
        return r

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: PoeParams) -> None:
        poe_ports = {x.port for x in drv.get_poe_ports()}
        missing = [x for x in p.ports if x not in poe_ports]
        if missing:
            raise PrecheckFailed(f"Port(s) without PoE: {', '.join(missing)}")

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: PoeParams) -> list[OperationResult]:
        return [drv.set_poe(x, enabled=p.enabled, priority=p.priority, allocation_method=p.allocation_method,
                            allocated_power_w=p.allocated_power_w) for x in p.ports]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: PoeParams) -> tuple[bool, dict]:
        state = {x.port: x for x in drv.get_poe_ports()}
        bad = []
        for port in p.ports:
            s = state.get(port)
            if s is None or (p.enabled is not None and s.enabled is not p.enabled) or \
                    (p.priority and s.priority != p.priority) or \
                    (p.allocation_method and s.allocation_method != p.allocation_method):
                bad.append(port)
        return not bad, {"mismatch": bad}


class PoeRestart(Operation):
    name = "poe_restart"
    title = "Restart PoE (power-cycle device)"
    permission = P.POE_MANAGE
    Params = PoeRestartParams
    refresh = "poe"
    warning = "Restarting PoE power-cycles the powered device and disconnects it until it boots again."

    def describe(self, p: PoeRestartParams) -> str:
        return f"Power-cycle PoE on port {p.port}"

    def assess(self, db: Session, sw: Switch, p: PoeRestartParams) -> Risk:
        r = Risk("medium", ["The powered device will be disconnected while it reboots"])
        if p.port in uplink_ports(db, sw):
            r.bump("high", "Port is an uplink (e.g. a PoE-powered switch or AP mesh link)")
        return r

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: PoeRestartParams) -> list[OperationResult]:
        return [drv.restart_poe(p.port)]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: PoeRestartParams) -> tuple[bool, dict]:
        s = {x.port: x for x in drv.get_poe_ports()}.get(p.port)
        return bool(s and s.enabled), {"enabled": s.enabled if s else None}


class _CliOperation(Operation):
    """Security/management features applied with allow-listed CLI and verified in the running-config."""

    permission = P.SECURITY_MANAGE
    expect_markers: ClassVar[tuple[str, ...]] = ()

    def lines(self, p: Any) -> list[str]:
        raise NotImplementedError

    def markers(self, p: Any) -> list[str]:
        return [line for line in self.lines(p) if not any(s in line for s in (" auth ", " key "))]

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: Any) -> list[OperationResult]:
        return [drv.apply_cli(self.lines(p))]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: Any) -> tuple[bool, dict]:
        text = drv.get_running_config().text
        missing = [m for m in self.markers(p) if m.split(" priv ")[0].split(" auth ")[0] not in text]
        return not missing, {"missing": missing}


class Sntp(_CliOperation):
    name = "sntp"
    title = "Configure SNTP"
    permission = P.SWITCH_MANAGE
    Params = SntpParams

    def assess(self, db: Session, sw: Switch, p: SntpParams) -> Risk:
        return Risk("medium", ["Changes time synchronisation (affects logs and certificates)"])

    def lines(self, p: SntpParams) -> list[str]:
        return cli.cmd_sntp(p.servers, p.timezone_minutes)


class SnmpUser(_CliOperation):
    name = "snmpv3_user"
    title = "Configure SNMPv3 user"
    Params = SnmpUserParams

    def assess(self, db: Session, sw: Switch, p: SnmpUserParams) -> Risk:
        return Risk("high", ["Changes management-plane credentials"])

    def lines(self, p: SnmpUserParams) -> list[str]:
        return cli.cmd_snmpv3_user(p.username, "sha", p.auth_password, "aes", p.priv_password, p.access)

    def markers(self, p: SnmpUserParams) -> list[str]:
        return ["snmpv3 enable", f"snmpv3 user {p.username}"]


class AuthorizedManagers(_CliOperation):
    name = "authorized_managers"
    title = "Restrict management access (authorized managers)"
    Params = AuthorizedManagerParams
    warning = ("If the application server or your workstation is outside the authorised range, management access "
               "is lost. Ensure out-of-band console access before applying.")

    def assess(self, db: Session, sw: Switch, p: AuthorizedManagerParams) -> Risk:
        return Risk("critical", ["Can lock administrators and this application out of the switch"])

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: AuthorizedManagerParams) -> None:
        from ipaddress import ip_address, ip_network

        from app.core.config import get_settings

        net = ip_network(f"{p.network}/{p.mask}", strict=False)
        mgmt_src = get_settings().allowed_client_networks
        server_ip = _server_source_ip(sw.mgmt_ip)
        if server_ip is None:
            raise PrecheckFailed("Cannot determine this server's source address towards the switch; refusing a "
                                 "change that could lock the application out")
        if ip_address(server_ip) not in net:
            raise PrecheckFailed(f"This server's source address {server_ip} is outside {net}; the change would "
                                 f"lock the application out (allowed networks: {mgmt_src})")

    def lines(self, p: AuthorizedManagerParams) -> list[str]:
        return cli.cmd_ip_authorized_manager(p.network, p.mask, p.access)


def _server_source_ip(target: str) -> str | None:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((target, 9))
            return s.getsockname()[0]
    except OSError:
        return None


class PortSecurity(_CliOperation):
    name = "port_security"
    title = "Configure port security (MAC restrictions)"
    Params = PortSecurityParams

    def assess(self, db: Session, sw: Switch, p: PortSecurityParams) -> Risk:
        r = Risk("high", ["Unauthorised MAC addresses will be blocked"])
        if uplink_ports(db, sw) & set(p.ports):
            r.bump("critical", "Port security on an uplink blocks all downstream devices")
        return r

    def lines(self, p: PortSecurityParams) -> list[str]:
        out: list[str] = []
        for port in p.ports:
            out += cli.cmd_port_security(port, p.learn_mode, p.address_limit, p.action)
        return out


class StpProtection(_CliOperation):
    name = "stp_protection"
    title = "STP edge/BPDU protection"
    Params = StpParams

    def assess(self, db: Session, sw: Switch, p: StpParams) -> Risk:
        r = Risk("high", ["STP change"])
        ups = uplink_ports(db, sw) & set(p.ports)
        if ups:
            r.bump("critical", f"BPDU protection on uplink(s) {sorted(ups)} disables them when a switch is detected")
        return r

    def lines(self, p: StpParams) -> list[str]:
        return cli.cmd_stp_protection(p.ports, p.bpdu_protection, p.admin_edge)


class DhcpSnooping(_CliOperation):
    name = "dhcp_snooping"
    title = "DHCP snooping"
    Params = DhcpSnoopingParams

    def assess(self, db: Session, sw: Switch, p: DhcpSnoopingParams) -> Risk:
        r = Risk("high", ["DHCP traffic is filtered on untrusted ports"])
        missing = uplink_ports(db, sw) - set(p.trusted_ports)
        if p.enabled and missing:
            r.bump("critical", f"Uplink(s) {sorted(missing)} are not trusted; clients may lose DHCP")
        return r

    def lines(self, p: DhcpSnoopingParams) -> list[str]:
        return cli.cmd_dhcp_snooping(p.enabled, p.vlans, p.trusted_ports)


class AaaServer(_CliOperation):
    name = "aaa_server"
    title = "RADIUS/TACACS+ server"
    Params = AaaServerParams

    def assess(self, db: Session, sw: Switch, p: AaaServerParams) -> Risk:
        return Risk("high", ["Adds an authentication server (does not change the login method by itself)"])

    def lines(self, p: AaaServerParams) -> list[str]:
        return cli.cmd_radius_server(p.host, p.key) if p.protocol == "radius" else cli.cmd_tacacs_server(p.host, p.key)

    def markers(self, p: AaaServerParams) -> list[str]:
        return [f"{'radius' if p.protocol == 'radius' else 'tacacs'}-server host {p.host}"]


class SshHardening(_CliOperation):
    name = "ssh_hardening"
    title = "Harden management protocols (SSH on, Telnet/HTTP off)"
    Params = EmptyParams

    def assess(self, db: Session, sw: Switch, p: EmptyParams) -> Risk:
        return Risk("high", ["Disables Telnet and plaintext web management"])

    def lines(self, p: EmptyParams) -> list[str]:
        return cli.cmd_ssh_hardening()

    def markers(self, p: EmptyParams) -> list[str]:
        return ["no telnet-server", "ip ssh filetransfer"]


class ConfigBackupOp(Operation):
    name = "config_backup"
    title = "Back up running configuration"
    permission = P.BACKUP_MANAGE
    Params = EmptyParams
    takes_backup = False
    saves_config = False
    refresh = ""

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: EmptyParams) -> list[OperationResult]:
        return []  # handled by the engine (backup taken as the operation itself)

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: EmptyParams) -> tuple[bool, dict]:
        return True, {}


class ConfigRestore(Operation):
    name = "config_restore"
    title = "Restore configuration (to startup-config)"
    permission = P.CONFIG_RESTORE
    Params = RestoreParams
    saves_config = False
    refresh = ""
    warning = ("The backup is written to the switch's startup-config. It becomes active only after the switch "
               "reloads, which is a separate, explicit action. Saving the running configuration before the reload "
               "would overwrite the restored startup-config.")

    def describe(self, p: RestoreParams) -> str:
        return f"Restore backup #{p.backup_id} to startup-config"

    def assess(self, db: Session, sw: Switch, p: RestoreParams) -> Risk:
        b = db.get(ConfigBackup, p.backup_id)
        r = Risk("critical", ["Replaces the startup configuration"])
        if b is None or b.switch_id != sw.id:
            r.reasons.append("Backup does not belong to this switch")
        return r

    def precheck(self, db: Session, sw: Switch, drv: SwitchDriver, p: RestoreParams) -> None:
        from app.services.backups import read_text

        b = db.get(ConfigBackup, p.backup_id)
        if b is None or b.switch_id != sw.id:
            raise PrecheckFailed("Backup does not belong to this switch")
        if b.verify_status != "verified":
            raise PrecheckFailed("Backup has not passed checksum verification")
        text = read_text(b)
        if "hostname" not in text:
            raise PrecheckFailed("Backup content is not a valid configuration")

    def execute(self, db: Session, sw: Switch, drv: SwitchDriver, p: RestoreParams) -> list[OperationResult]:
        from app.services.backups import read_text

        b = db.get(ConfigBackup, p.backup_id)
        assert b is not None
        return [drv.upload_startup_config(read_text(b))]

    def verify(self, db: Session, sw: Switch, drv: SwitchDriver, p: RestoreParams) -> tuple[bool, dict]:
        from app.core.crypto import sha256_hex
        from app.drivers.aruba.aos_switch.configuration import normalize_config
        from app.services.backups import read_text

        b = db.get(ConfigBackup, p.backup_id)
        assert b is not None
        startup = drv.get_startup_config().text
        expected = normalize_config(read_text(b))
        ok = sha256_hex(normalize_config(startup).encode()) == sha256_hex(expected.encode())
        if ok:
            from app.db.base import utcnow

            b.restore_tested = True
            b.restore_tested_at = utcnow()
        return ok, {"startup_matches_backup": ok}


REGISTRY: dict[str, Operation] = {op.name: op for op in [
    PortAdmin(), PortDescription(), PortSpeed(), PortVlan(), VlanCreate(), VlanDelete(), PoeConfig(), PoeRestart(),
    Sntp(), SnmpUser(), AuthorizedManagers(), PortSecurity(), StpProtection(), DhcpSnooping(), AaaServer(),
    SshHardening(), ConfigBackupOp(), ConfigRestore(),
]}

# Operations that may be run against many switches at once (bulk operations page).
BULK_OPERATIONS = {"vlan_create", "vlan_delete", "port_vlan", "port_description", "sntp", "snmpv3_user",
                   "ssh_hardening", "stp_protection", "dhcp_snooping", "aaa_server", "config_backup",
                   "authorized_managers", "poe_config", "port_admin"}

SECRET_PARAMS = {"auth_password", "priv_password", "key"}
