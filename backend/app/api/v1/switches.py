from __future__ import annotations

import ipaddress
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require, require_any
from app.api.serializers import port_out, switch_out
from app.core.config import get_settings
from app.core.errors import bad_request, conflict, not_found
from app.core.permissions import P
from app.db.session import get_db
from app.drivers.aruba.aos_switch import cli_commands as cli
from app.drivers.base import DriverError
from app.models import (
    MacLearnedEntry,
    PoeConfiguration,
    Site,
    Switch,
    SwitchEvent,
    SwitchGroup,
    SwitchGroupMember,
    SwitchNeighbor,
    SwitchPort,
    SwitchVlan,
    User,
)
from app.services import audit, polling
from app.services import settings as sysset

log = logging.getLogger(__name__)
router = APIRouter(prefix="/switches", tags=["switches"])


class SwitchIn(BaseModel):
    hostname: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.\-]+$")
    mgmt_ip: str
    site_id: int | None = None
    location: str = Field(default="", max_length=128)
    building: str = Field(default="", max_length=64)
    floor: str = Field(default="", max_length=32)
    department: str = Field(default="", max_length=64)
    mgmt_vlan: int | None = Field(default=None, ge=1, le=4094)
    uplink_ports: list[str] = Field(default_factory=list)
    monitoring_enabled: bool = True
    protocols: dict[str, bool] = Field(default_factory=lambda: {"rest": True, "snmp": True, "ssh": True})
    notes: str = Field(default="", max_length=2000)
    group_ids: list[int] = Field(default_factory=list)

    @field_validator("mgmt_ip")
    @classmethod
    def _ip(cls, v: str) -> str:
        try:
            return str(ipaddress.ip_address(v))
        except ValueError as exc:
            raise ValueError("Invalid IP address") from exc

    @field_validator("uplink_ports")
    @classmethod
    def _ports(cls, v: list[str]) -> list[str]:
        for p in v:
            cli.port(p)
        return sorted(set(v), key=lambda x: (len(x), x))

    @field_validator("protocols")
    @classmethod
    def _protocols(cls, v: dict[str, bool]) -> dict[str, bool]:
        if set(v) - {"rest", "snmp", "ssh"}:
            raise ValueError("Only rest, snmp and ssh are supported management protocols (Telnet is never used)")
        return {k: bool(v.get(k, False)) for k in ("rest", "snmp", "ssh")}


class SwitchPatch(BaseModel):
    hostname: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.\-]+$")
    mgmt_ip: str | None = None
    site_id: int | None = None
    location: str | None = Field(default=None, max_length=128)
    building: str | None = Field(default=None, max_length=64)
    floor: str | None = Field(default=None, max_length=32)
    department: str | None = Field(default=None, max_length=64)
    mgmt_vlan: int | None = Field(default=None, ge=1, le=4094)
    uplink_ports: list[str] | None = None
    monitoring_enabled: bool | None = None
    protocols: dict[str, bool] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    group_ids: list[int] | None = None

    _ip = field_validator("mgmt_ip")(lambda cls, v: SwitchIn._ip(v) if v is not None else v)
    _ports = field_validator("uplink_ports")(lambda cls, v: SwitchIn._ports(v) if v is not None else v)
    _protocols = field_validator("protocols")(lambda cls, v: SwitchIn._protocols(v) if v is not None else v)


class DeleteConfirm(BaseModel):
    confirm_hostname: str


class DiscoverIn(BaseModel):
    cidr: str
    add: bool = False

    @field_validator("cidr")
    @classmethod
    def _cidr(cls, v: str) -> str:
        net = ipaddress.ip_network(v, strict=False)
        if net.num_addresses > 256:
            raise ValueError("Discovery is limited to /24 (256 addresses) per run")
        return str(net)


def _get(db: Session, switch_id: int) -> Switch:
    sw = db.get(Switch, switch_id)
    if sw is None:
        raise not_found("Switch")
    return sw


def _groups_for(db: Session, ids: list[int]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    rows = db.execute(select(SwitchGroupMember.switch_id, SwitchGroup.id, SwitchGroup.name)
                      .join(SwitchGroup, SwitchGroup.id == SwitchGroupMember.group_id)
                      .where(SwitchGroupMember.switch_id.in_(ids))).all()
    for sid, gid, name in rows:
        out.setdefault(sid, []).append({"id": gid, "name": name})
    return out


def _set_groups(db: Session, sw: Switch, group_ids: list[int]) -> None:
    db.query(SwitchGroupMember).filter(SwitchGroupMember.switch_id == sw.id).delete()
    for gid in set(group_ids):
        if db.get(SwitchGroup, gid) is None:
            raise bad_request(f"Group {gid} does not exist")
        db.add(SwitchGroupMember(group_id=gid, switch_id=sw.id))


@router.get("")
def list_switches(q: str | None = None, status: str | None = None, site_id: int | None = None,
                  group_id: int | None = None, building: str | None = None, simulated: bool | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(100, ge=1, le=500),
                  sort: Literal["hostname", "mgmt_ip", "status", "location"] = "hostname",
                  user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> dict:
    stmt = select(Switch)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(Switch.hostname).like(like), Switch.mgmt_ip.like(like),
                              func.lower(Switch.serial_number).like(like), func.lower(Switch.location).like(like),
                              func.lower(Switch.department).like(like), func.lower(Switch.base_mac).like(like)))
    if status:
        stmt = stmt.where(Switch.status == status)
    if site_id:
        stmt = stmt.where(Switch.site_id == site_id)
    if building:
        stmt = stmt.where(Switch.building == building)
    if simulated is not None:
        stmt = stmt.where(Switch.is_simulated.is_(simulated))
    if group_id:
        stmt = stmt.where(Switch.id.in_(select(SwitchGroupMember.switch_id).where(SwitchGroupMember.group_id == group_id)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(getattr(Switch, sort), Switch.id).offset((page - 1) * page_size)
                      .limit(page_size)).unique().scalars().all()
    stale = int(sysset.get(db, "metrics.stale_after_seconds"))
    groups = _groups_for(db, [s.id for s in rows])
    port_counts = dict(db.execute(select(SwitchPort.switch_id, func.count()).where(
        SwitchPort.switch_id.in_([s.id for s in rows])).group_by(SwitchPort.switch_id)).all())
    up_counts = dict(db.execute(select(SwitchPort.switch_id, func.count()).where(
        SwitchPort.switch_id.in_([s.id for s in rows]), SwitchPort.oper_up.is_(True)).group_by(SwitchPort.switch_id)).all())
    items = []
    for s in rows:
        d = switch_out(s, stale, groups.get(s.id))
        d["ports_total"] = port_counts.get(s.id, 0)
        d["ports_up"] = up_counts.get(s.id, 0)
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_switch(body: SwitchIn, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    if db.execute(select(Switch).where(Switch.mgmt_ip == body.mgmt_ip)).first():
        raise conflict("A switch with this management IP already exists", "duplicate_ip")
    if body.site_id and db.get(Site, body.site_id) is None:
        raise bad_request("Site does not exist")
    data = body.model_dump(exclude={"group_ids"})
    sw = Switch(**data, driver="aruba_aos_s", is_simulated=False, status="unknown")
    db.add(sw)
    db.flush()
    _set_groups(db, sw, body.group_ids)
    audit.record(db, action="switch.create", category="operational", actor=user, target_type="switch",
                 target_id=sw.id, switch_id=sw.id, details={"hostname": sw.hostname, "mgmt_ip": sw.mgmt_ip})
    db.commit()
    db.refresh(sw)
    return switch_out(sw)


@router.get("/{switch_id}")
def get_switch(switch_id: int, user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    stale = int(sysset.get(db, "metrics.stale_after_seconds"))
    d = switch_out(sw, stale, _groups_for(db, [sw.id]).get(sw.id))
    d["ports_total"] = db.execute(select(func.count()).where(SwitchPort.switch_id == sw.id)).scalar_one()
    d["ports_up"] = db.execute(select(func.count()).where(SwitchPort.switch_id == sw.id,
                                                          SwitchPort.oper_up.is_(True))).scalar_one()
    d["vlan_count"] = db.execute(select(func.count()).where(SwitchVlan.switch_id == sw.id)).scalar_one()
    d["device_count"] = db.execute(select(func.count()).where(MacLearnedEntry.switch_id == sw.id,
                                                              MacLearnedEntry.active.is_(True))).scalar_one()
    return d


@router.patch("/{switch_id}")
def update_switch(switch_id: int, body: SwitchPatch, user: User = Depends(require(P.SWITCH_MANAGE)),
                  db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    data = body.model_dump(exclude_unset=True)
    group_ids = data.pop("group_ids", None)
    if "mgmt_ip" in data and data["mgmt_ip"] != sw.mgmt_ip:
        if sw.is_simulated:
            raise bad_request("The management IP of a simulated switch cannot be changed")
        if db.execute(select(Switch).where(Switch.mgmt_ip == data["mgmt_ip"], Switch.id != sw.id)).first():
            raise conflict("A switch with this management IP already exists", "duplicate_ip")
        # A new address means a new SSH host key must be trusted again.
        sw.ssh_host_key = sw.ssh_host_key_fingerprint = None
        sw.ssh_host_key_trusted = False
    changes = {k: [getattr(sw, k), v] for k, v in data.items() if getattr(sw, k) != v}
    for k, v in data.items():
        setattr(sw, k, v)
    if group_ids is not None:
        _set_groups(db, sw, group_ids)
        changes["groups"] = group_ids
    if "uplink_ports" in data:
        for p in db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id)).scalars():
            p.is_uplink = p.name in (sw.uplink_ports or [])
    audit.record(db, action="switch.update", category="operational", actor=user, target_type="switch",
                 target_id=sw.id, switch_id=sw.id, details={"changes": changes})
    db.commit()
    db.refresh(sw)
    return switch_out(sw)


@router.delete("/{switch_id}")
def delete_switch(switch_id: int, body: DeleteConfirm, user: User = Depends(require(P.SWITCH_DELETE)),
                  db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    if body.confirm_hostname != sw.hostname:
        raise bad_request("Type the switch hostname to confirm deletion", "confirmation_mismatch")
    audit.record(db, action="switch.delete", category="operational", actor=user, target_type="switch",
                 target_id=sw.id, details={"hostname": sw.hostname, "mgmt_ip": sw.mgmt_ip})
    from app.models import ConfigBackup
    from app.services.storage import get_store

    keys = list(db.execute(select(ConfigBackup.storage_key).where(ConfigBackup.switch_id == sw.id)).scalars())
    db.delete(sw)
    db.commit()
    # The backup rows are removed with the switch; remove their encrypted objects too (best effort, after commit).
    store = get_store()
    for key in keys:
        try:
            store.delete(key)
        except Exception:  # noqa: BLE001 - an orphaned encrypted object is harmless; the switch is already deleted
            log.warning("could not delete backup object for deleted switch %s", sw.id)
    return {"ok": True}


@router.post("/{switch_id}/poll")
def poll_now(switch_id: int, category: str = "inventory", user: User = Depends(require(P.SWITCH_MANAGE)),
             db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    if category not in polling.CATEGORIES:
        raise bad_request("Unknown polling category")
    if not sw.monitoring_enabled:
        raise conflict("Monitoring is disabled for this switch")
    db.close()
    result = polling.poll_switch(switch_id, category)
    return result


@router.post("/{switch_id}/ssh-host-key/fetch")
def fetch_host_key(switch_id: int, user: User = Depends(require(P.CREDENTIAL_MANAGE)),
                   db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    if sw.is_simulated:
        from app.drivers.aruba.aos_switch.ssh_client import fingerprint
        from app.drivers.simulator.driver import SIM_HOST_KEY

        key, fp = SIM_HOST_KEY, fingerprint(SIM_HOST_KEY.split()[1])
    else:
        from app.drivers.aruba.aos_switch.ssh_client import fetch_host_key as fetch

        try:
            key, fp = fetch(sw.mgmt_ip, timeout=get_settings().device_timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            raise bad_request(f"Could not retrieve host key: {exc.__class__.__name__}", "host_key_fetch_failed") from exc
    changed = sw.ssh_host_key is not None and sw.ssh_host_key != key
    sw.ssh_host_key, sw.ssh_host_key_fingerprint, sw.ssh_host_key_trusted = key, fp, False
    audit.record(db, action="switch.ssh_host_key_fetched", category="security", actor=user, target_type="switch",
                 target_id=sw.id, switch_id=sw.id, details={"fingerprint": fp, "changed": changed})
    db.commit()
    return {"fingerprint": fp, "trusted": False, "changed": changed,
            "message": "Compare the fingerprint with 'show crypto host-public-key fingerprint' on the switch console "
                       "before trusting it."}


@router.post("/{switch_id}/ssh-host-key/trust")
def trust_host_key(switch_id: int, body: dict, user: User = Depends(require(P.CREDENTIAL_MANAGE)),
                   db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    if not sw.ssh_host_key or body.get("fingerprint") != sw.ssh_host_key_fingerprint:
        raise bad_request("Fingerprint does not match the fetched host key", "fingerprint_mismatch")
    sw.ssh_host_key_trusted = True
    audit.record(db, action="switch.ssh_host_key_trusted", category="security", actor=user, target_type="switch",
                 target_id=sw.id, switch_id=sw.id, details={"fingerprint": sw.ssh_host_key_fingerprint})
    db.commit()
    return {"trusted": True}


@router.post("/discover")
def discover(body: DiscoverIn, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    """SNMPv3 discovery with the fleet default monitoring credential. Only responding Aruba AOS-Switch devices are
    reported; nothing is added unless add=true."""
    from concurrent.futures import ThreadPoolExecutor

    from app.drivers.aruba.aos_switch import system as sysmod
    from app.drivers.aruba.aos_switch.snmp_client import PySnmpTransport, SnmpClient, SnmpV3Credentials
    from app.services.credentials import resolve

    cred = resolve(db, 0, "snmpv3", "monitor")
    if cred is None:
        raise bad_request("Configure a default SNMPv3 monitoring credential before discovery")
    creds = SnmpV3Credentials(cred[0], cred[1]["auth_password"], cred[1]["priv_password"],
                              cred[2].get("auth_protocol", "sha"), cred[2].get("priv_protocol", "aes"))
    net = ipaddress.ip_network(body.cidr, strict=False)
    existing = {s for (s,) in db.execute(select(Switch.mgmt_ip)).all()}
    hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]

    def probe(ip: str) -> dict | None:
        try:
            info = sysmod.snmp_system(SnmpClient(PySnmpTransport(ip, creds, timeout=1.5, retries=0)))
        except DriverError:
            return None
        except Exception:  # noqa: BLE001
            return None
        return {"mgmt_ip": ip, "hostname": info.hostname, "product_number": info.product_number,
                "firmware": info.firmware, "description": info.description, "exists": ip in existing}

    with ThreadPoolExecutor(max_workers=32) as pool:
        found = [r for r in pool.map(probe, hosts) if r]
    added = []
    if body.add:
        for f in found:
            if f["exists"] or not f["product_number"]:
                continue
            sw = Switch(hostname=(f["hostname"] or f["mgmt_ip"]).replace(" ", "_")[:128], mgmt_ip=f["mgmt_ip"],
                        product_number=f["product_number"], firmware=f["firmware"], status="unknown")
            db.add(sw)
            added.append(f["mgmt_ip"])
    audit.record(db, action="switch.discover", category="operational", actor=user,
                 details={"cidr": body.cidr, "found": len(found), "added": added})
    db.commit()
    return {"cidr": body.cidr, "scanned": len(hosts), "found": found, "added": added}


# ------------------------------------------------------------------ per-switch data

@router.get("/{switch_id}/ports")
def ports(switch_id: int, user: User = Depends(require(P.PORT_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    sw = _get(db, switch_id)
    from app.core.permissions import has_permission

    poe = {p.port_name: p for p in db.execute(select(PoeConfiguration).where(PoeConfiguration.switch_id == sw.id)).scalars()}
    macs: dict[str, list[dict]] = {}
    if has_permission(user.role, P.DEVICE_VIEW):
        for m in db.execute(select(MacLearnedEntry).where(MacLearnedEntry.switch_id == sw.id,
                                                          MacLearnedEntry.active.is_(True))).scalars():
            macs.setdefault(m.port_name, []).append({"mac": m.mac, "vlan_id": m.vlan_id, "vendor": m.vendor})
    nbrs: dict[str, list[dict]] = {}
    for n in db.execute(select(SwitchNeighbor).where(SwitchNeighbor.switch_id == sw.id)).scalars():
        nbrs.setdefault(n.local_port, []).append({"system_name": n.system_name, "remote_port": n.remote_port,
                                                  "chassis_id": n.chassis_id, "remote_switch_id": n.remote_switch_id,
                                                  "source": n.source})
    rows = db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id)
                      .order_by(SwitchPort.port_number.nulls_last(), SwitchPort.name)).scalars().all()
    out = []
    for p in rows:
        pc = poe.get(p.name)
        poe_d = None
        if pc:
            poe_d = {"enabled": pc.enabled, "priority": pc.priority, "allocation_method": pc.allocation_method,
                     "allocated_power_w": pc.allocated_power_w, "power_drawn_w": pc.power_drawn_w,
                     "detection_status": pc.detection_status, "power_class": pc.power_class, "fault": pc.fault,
                     "updated_at": pc.updated_at}
        out.append(port_out(p, poe_d, macs.get(p.name), nbrs.get(p.name)))
    return out


@router.get("/{switch_id}/vlans")
def switch_vlans(switch_id: int, user: User = Depends(require(P.VLAN_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    sw = _get(db, switch_id)
    ports_rows = db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id)).scalars().all()
    out = []
    for v in db.execute(select(SwitchVlan).where(SwitchVlan.switch_id == sw.id).order_by(SwitchVlan.vlan_id)).scalars():
        out.append({"vlan_id": v.vlan_id, "name": v.name, "status": v.status, "is_management": v.is_management,
                    "untagged_ports": sorted([p.name for p in ports_rows if p.untagged_vlan == v.vlan_id],
                                             key=lambda x: (len(x), x)),
                    "tagged_ports": sorted([p.name for p in ports_rows if v.vlan_id in (p.tagged_vlans or [])],
                                           key=lambda x: (len(x), x)),
                    "updated_at": v.updated_at})
    return out


@router.get("/{switch_id}/poe")
def switch_poe(switch_id: int, user: User = Depends(require(P.POE_VIEW)), db: Session = Depends(get_db)) -> dict:
    sw = _get(db, switch_id)
    rows = db.execute(select(PoeConfiguration).where(PoeConfiguration.switch_id == sw.id)).scalars().all()
    rows = sorted(rows, key=lambda r: int(r.port_name) if r.port_name.isdigit() else 999)
    return {"budget_w": sw.poe_budget_w, "consumed_w": sw.poe_consumed_w, "metrics_at": sw.metrics_at,
            "ports": [{"port": r.port_name, "enabled": r.enabled, "priority": r.priority,
                       "allocation_method": r.allocation_method, "allocated_power_w": r.allocated_power_w,
                       "power_drawn_w": r.power_drawn_w, "detection_status": r.detection_status,
                       "power_class": r.power_class, "fault": r.fault, "updated_at": r.updated_at} for r in rows]}


@router.get("/{switch_id}/neighbors")
def neighbors(switch_id: int, user: User = Depends(require(P.TOPOLOGY_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    _get(db, switch_id)
    rows = db.execute(select(SwitchNeighbor).where(SwitchNeighbor.switch_id == switch_id)).scalars().all()
    return [{"id": n.id, "local_port": n.local_port, "chassis_id": n.chassis_id, "remote_port": n.remote_port,
             "remote_port_desc": n.remote_port_desc, "system_name": n.system_name,
             "system_description": n.system_description, "mgmt_address": n.mgmt_address,
             "capabilities": n.capabilities, "remote_switch_id": n.remote_switch_id, "source": n.source,
             "first_seen": n.first_seen, "last_seen": n.last_seen} for n in rows]


@router.get("/{switch_id}/events")
def switch_events(switch_id: int, limit: int = Query(100, le=1000), user: User = Depends(require(P.EVENT_VIEW)),
                  db: Session = Depends(get_db)) -> list[dict]:
    _get(db, switch_id)
    rows = db.execute(select(SwitchEvent).where(SwitchEvent.switch_id == switch_id)
                      .order_by(SwitchEvent.ts.desc()).limit(limit)).scalars().all()
    return [{"id": e.id, "ts": e.ts, "severity": e.severity, "type": e.type, "port_name": e.port_name,
             "message": e.message} for e in rows]


@router.get("/{switch_id}/security")
def switch_security(switch_id: int, user: User = Depends(require_any(P.SECURITY_MANAGE, P.SWITCH_VIEW)),
                    db: Session = Depends(get_db)) -> dict:
    """Security posture derived from the latest verified configuration backup (no device access)."""
    from app.services import backups as bsvc

    sw = _get(db, switch_id)
    b = bsvc.latest(db, sw.id)
    posture: dict = {"backup_id": None, "backup_at": None, "checks": []}
    if b is not None and b.verify_status == "verified":
        text = bsvc.read_text(b)
        checks = [
            ("telnet_disabled", "Telnet disabled", "no telnet-server" in text),
            ("plaintext_web_disabled", "Plaintext web management disabled", "no web-management plaintext" in text),
            ("ssh_filetransfer", "SSH/SFTP file transfer enabled", "ip ssh filetransfer" in text),
            ("snmpv3", "SNMPv3 enabled", "snmpv3 enable" in text),
            ("snmpv1v2_community", "No SNMPv1/v2c community configured", "snmp-server community" not in text),
            ("authorized_managers", "Management access restricted (authorized managers)",
             "ip authorized-managers" in text),
            ("sntp", "Time synchronisation (SNTP)", "sntp server" in text or "timesync sntp" in text),
            ("dhcp_snooping", "DHCP snooping", "dhcp-snooping" in text and "no dhcp-snooping" not in text),
            ("bpdu_protection", "BPDU protection on edge ports", "bpdu-protection" in text),
            ("port_security", "Port security", "port-security" in text),
            ("aaa", "RADIUS/TACACS+ server configured", "radius-server host" in text or "tacacs-server host" in text),
        ]
        posture = {"backup_id": b.id, "backup_at": b.created_at,
                   "checks": [{"key": k, "label": label, "ok": ok} for k, label, ok in checks]}
    posture["ssh_host_key_trusted"] = sw.ssh_host_key_trusted
    posture["ssh_host_key_fingerprint"] = sw.ssh_host_key_fingerprint
    posture["mgmt_vlan"] = sw.mgmt_vlan
    return posture
