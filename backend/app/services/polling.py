"""Monitoring engine.

Each category (availability, counters, health, poe, temperature, mac, lldp, inventory) polls every
monitoring-enabled switch with bounded concurrency (settings.poll_concurrency threads, one DB session and one
driver per switch). A Redis lock per (switch, category) prevents overlapping polls when a switch is slow, so the
application never stacks requests against a struggling device.

All stored values come from the device. Anything a device did not report stays NULL and is displayed as
"unavailable"; stale values are flagged by age (metrics.stale_after_seconds).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.db.session import session_factory
from app.drivers.aruba.aos_switch import models as hwmodels
from app.drivers.base import DriverError, SwitchDriver
from app.models import (
    MacLearnedEntry,
    OuiVendor,
    PoeConfiguration,
    PoeMetric,
    PollingJob,
    PortMetric,
    PortVlanMembership,
    Switch,
    SwitchModel,
    SwitchNeighbor,
    SwitchPort,
    SwitchVlan,
)
from app.services import alerts
from app.services import settings as sysset
from app.services.devices import driver_for

log = logging.getLogger(__name__)
OFFLINE_AFTER_FAILURES = 2
COUNTER_MAX = 2**64


# ------------------------------------------------------------------ helpers

def _switch_metric(db: Session, sw: Switch, **values: Any) -> None:
    from app.models import SwitchMetric

    stmt = pg_insert(SwitchMetric).values(switch_id=sw.id, ts=utcnow(), **values)
    db.execute(stmt.on_conflict_do_nothing())


CREDENTIAL_ERROR_CODES = ("auth_failed", "no_credentials", "host_key_untrusted", "host_key_mismatch")


def set_credential_problem(sw: Switch, protocol: str, exc: DriverError | None) -> None:
    """Remember (or clear) a monitoring credential the switch refused, per protocol, for the switch page and the
    Device credentials page. Kept in switches.capabilities so it survives until the protocol works again."""
    if protocol not in ("rest", "snmp", "ssh"):
        return
    caps = dict(sw.capabilities or {})
    problems = dict(caps.get("credential_problems") or {})
    if exc is None:
        if protocol not in problems:
            return
        problems.pop(protocol)
    else:
        prev = problems.get(protocol) or {}
        problems[protocol] = {"code": exc.code, "message": exc.message[:255],
                              "since": prev.get("since") or utcnow().isoformat(), "last_seen": utcnow().isoformat()}
    caps["credential_problems"] = problems
    sw.capabilities = caps


def _mark_failure(db: Session, sw: Switch, exc: DriverError) -> None:
    sw.poll_failures = (sw.poll_failures or 0) + 1
    sw.last_poll_at = utcnow()
    sw.status_reason = f"{exc.protocol or 'device'}: {exc.message}"[:255]
    if exc.code in CREDENTIAL_ERROR_CODES and exc.code != "no_credentials":
        set_credential_problem(sw, exc.protocol, exc)
    if exc.code in (*CREDENTIAL_ERROR_CODES, "simulator_disabled"):
        # Reachable but misconfigured: warning, not offline.
        if sw.status != "offline":
            sw.status = "warning"
        return
    if sw.poll_failures >= OFFLINE_AFTER_FAILURES and sw.status != "offline":
        previous = sw.status
        sw.status = "offline"
        _switch_metric(db, sw, reachable=False)
        alerts.event(db, type="switch.offline", severity="critical", switch_id=sw.id,
                     message=f"{sw.hostname} ({sw.mgmt_ip}) is unreachable: {exc.message}")
        alerts.raise_alert(db, type="switch_offline", switch=sw,
                           message=f"Switch {sw.hostname} ({sw.mgmt_ip}) is offline",
                           details={"error": exc.to_dict(), "previous_status": previous})
    elif sw.status == "offline":
        _switch_metric(db, sw, reachable=False)


def _mark_success(db: Session, sw: Switch, latency_ms: float | None = None) -> None:
    was_offline = sw.status == "offline"
    sw.poll_failures = 0
    sw.last_poll_at = sw.last_success_at = utcnow()
    sw.status_reason = ""
    if sw.status in ("offline", "unknown", "warning"):
        sw.status = "online"
    if was_offline:
        alerts.event(db, type="switch.recovered", severity="info", switch_id=sw.id,
                     message=f"{sw.hostname} ({sw.mgmt_ip}) is reachable again")
        alerts.resolve(db, type="switch_offline", switch=sw, message=f"Switch {sw.hostname} recovered")
        alerts.raise_alert(db, type="switch_recovered", switch=sw, message=f"Switch {sw.hostname} recovered",
                           dedup_suffix=str(int(time.time())))
        # "recovered" is informational; close it immediately so it doesn't linger as an open alert.
        alerts.resolve(db, type="switch_recovered", switch=sw, dedup_suffix=str(int(time.time())),
                       message=f"Switch {sw.hostname} recovered")


def _port_map(db: Session, sw: Switch) -> dict[str, SwitchPort]:
    return {p.name: p for p in db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id)).scalars()}


# ------------------------------------------------------------------ categories

def poll_availability(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    """Availability + port status (admin/oper/speed/duplex)."""
    t0 = time.monotonic()
    status = drv.get_port_status()
    latency = round((time.monotonic() - t0) * 1000, 1)
    _mark_success(db, sw, latency)
    ports = _port_map(db, sw)
    now = utcnow()
    flap_threshold = int(sysset.get(db, "alerts.flap_threshold"))
    changed = 0
    for p in status:
        row = ports.get(p.name)
        if row is None:
            if p.if_index is None:
                continue
            row = SwitchPort(switch_id=sw.id, if_index=p.if_index, name=p.name,
                             port_number=hwmodels.port_number(p.name), description=p.description,
                             is_uplink=p.name in (sw.uplink_ports or []), tagged_vlans=[])
            db.add(row)
            ports[p.name] = row
        prev_oper = row.oper_up
        row.admin_up = p.admin_up
        row.oper_up = p.oper_up
        row.speed_mbps = p.speed_mbps
        row.duplex = p.duplex
        if p.description:
            row.description = p.description
        if prev_oper is not None and p.oper_up is not None and prev_oper != p.oper_up:
            changed += 1
            # Flap counting over a 10-minute window.
            if row.status_changed_at and now - row.status_changed_at < timedelta(minutes=10):
                row.flap_count += 1
            else:
                row.flap_count = 1
            row.status_changed_at = now
            alerts.event(db, type="port.up" if p.oper_up else "port.down", switch_id=sw.id, port_name=p.name,
                         severity="info" if p.oper_up else ("major" if row.is_uplink else "info"),
                         message=f"{sw.hostname} port {p.name} link {'up' if p.oper_up else 'down'}")
            if row.is_uplink and p.admin_up:
                if not p.oper_up:
                    alerts.raise_alert(db, type="port_down", switch=sw, port_name=p.name,
                                       message=f"Uplink {p.name} on {sw.hostname} is down")
                else:
                    alerts.resolve(db, type="port_down", switch=sw, port_name=p.name)
            if row.flap_count >= flap_threshold:
                alerts.raise_alert(db, type="port_flapping", switch=sw, port_name=p.name,
                                   message=f"Port {p.name} on {sw.hostname} is flapping ({row.flap_count} changes in 10 min)")
        elif row.status_changed_at and now - row.status_changed_at > timedelta(minutes=10) and row.flap_count:
            row.flap_count = 0
            alerts.resolve(db, type="port_flapping", switch=sw, port_name=p.name)
    _switch_metric(db, sw, reachable=True, latency_ms=latency)
    return {"ports": len(status), "changes": changed}


def poll_counters(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    counters = drv.get_port_counters()
    _mark_success(db, sw)
    set_credential_problem(sw, "snmp", None)
    ports = _port_map(db, sw)
    now = utcnow()
    ts = now.timestamp()
    err_threshold = float(sysset.get(db, "alerts.error_rate_threshold"))
    total_in = total_out = 0.0
    have_rates = False
    rows = []
    for c in counters:
        name = c.name or str(c.if_index)
        row = ports.get(name)
        prev = row.last_counters if row is not None else {}
        in_bps = out_bps = None
        err_rate = None
        if prev and prev.get("ts") and ts - prev["ts"] > 0:
            dt = ts - prev["ts"]

            def delta(cur: int | None, old: int | None) -> int | None:
                if cur is None or old is None:
                    return None
                d = cur - old
                return d + COUNTER_MAX if d < 0 else d  # 64-bit wrap

            din = delta(c.in_octets, prev.get("in"))
            dout = delta(c.out_octets, prev.get("out"))
            in_bps = din * 8 / dt if din is not None else None
            out_bps = dout * 8 / dt if dout is not None else None
            derr = (delta(c.in_errors, prev.get("in_err")) or 0) + (delta(c.out_errors, prev.get("out_err")) or 0)
            err_rate = derr / dt * 60
        if row is not None:
            row.last_counters = {"ts": ts, "in": c.in_octets, "out": c.out_octets, "in_err": c.in_errors,
                                 "out_err": c.out_errors}
            row.in_bps, row.out_bps = in_bps, out_bps
            row.in_errors, row.out_errors = c.in_errors, c.out_errors
            row.in_discards, row.out_discards = c.in_discards, c.out_discards
            if err_rate is not None:
                if err_rate >= err_threshold:
                    alerts.raise_alert(db, type="high_errors", switch=sw, port_name=name,
                                       message=f"Port {name} on {sw.hostname}: {err_rate:.0f} errors/min",
                                       details={"errors_per_minute": round(err_rate, 1)})
                else:
                    alerts.resolve(db, type="high_errors", switch=sw, port_name=name)
        if in_bps is not None:
            have_rates = True
            # Aggregate only access/edge ports to avoid double counting traffic crossing uplinks.
            if row is None or not row.is_uplink:
                total_in += in_bps
                total_out += out_bps or 0
        rows.append({"switch_id": sw.id, "if_index": c.if_index, "ts": now, "oper_up": c.oper_up,
                     "in_octets": c.in_octets, "out_octets": c.out_octets, "in_bps": in_bps, "out_bps": out_bps,
                     "in_errors": c.in_errors, "out_errors": c.out_errors, "in_discards": c.in_discards,
                     "out_discards": c.out_discards})
    if rows:
        db.execute(pg_insert(PortMetric).values(rows).on_conflict_do_nothing())
    if have_rates:
        _switch_metric(db, sw, reachable=True, in_bps=total_in, out_bps=total_out)
    return {"interfaces": len(counters), "rates": have_rates}


def poll_health(db: Session, sw: Switch, drv: SwitchDriver, include_temperature: bool = False) -> dict:
    h = drv.get_health(include_temperature=include_temperature)
    _mark_success(db, sw)
    set_credential_problem(sw, "snmp", None)
    sw.cpu_pct, sw.mem_pct, sw.uptime_seconds = h.cpu_pct, h.mem_pct, h.uptime_seconds
    if include_temperature:
        sw.temperature_c = h.temperature_c
    sw.metrics_at = utcnow()
    cpu_t = float(sysset.get(db, "alerts.cpu_threshold"))
    mem_t = float(sysset.get(db, "alerts.memory_threshold"))
    for typ, val, thr, label in (("high_cpu", h.cpu_pct, cpu_t, "CPU"), ("high_memory", h.mem_pct, mem_t, "Memory")):
        if val is None:
            continue
        if val >= thr:
            alerts.raise_alert(db, type=typ, switch=sw, message=f"{label} on {sw.hostname} is {val:.0f}% (>= {thr:.0f}%)",
                               details={"value": val, "threshold": thr})
        else:
            alerts.resolve(db, type=typ, switch=sw)
    _switch_metric(db, sw, reachable=True, cpu_pct=h.cpu_pct, mem_pct=h.mem_pct,
                   temperature_c=h.temperature_c if include_temperature else None, uptime_seconds=h.uptime_seconds)
    return {"cpu": h.cpu_pct, "mem": h.mem_pct, "temperature": h.temperature_c}


def poll_temperature(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    return poll_health(db, sw, drv, include_temperature=True)


def poll_poe(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    summary = drv.get_poe_summary()
    try:
        ports = drv.get_poe_ports()
    except DriverError as exc:
        if exc.code != "unsupported":
            raise
        ports = []
    _mark_success(db, sw)
    sw.poe_budget_w, sw.poe_consumed_w = summary.budget_w, summary.consumed_w
    now = utcnow()
    existing = {p.port_name: p for p in db.execute(select(PoeConfiguration).where(
        PoeConfiguration.switch_id == sw.id)).scalars()}
    metric_rows = []
    for p in ports:
        row = existing.get(p.port)
        if row is None:
            row = PoeConfiguration(switch_id=sw.id, port_name=p.port)
            db.add(row)
        row.enabled, row.priority, row.allocation_method = p.enabled, p.priority, p.allocation_method
        row.allocated_power_w, row.power_drawn_w = p.allocated_power_w, p.power_drawn_w
        row.detection_status, row.power_class, row.fault = p.detection_status, p.power_class, p.fault
        if p.detection_status == "fault":
            alerts.raise_alert(db, type="poe_fault", switch=sw, port_name=p.port,
                               message=f"PoE fault on {sw.hostname} port {p.port}", details={"fault": p.fault})
        else:
            alerts.resolve(db, type="poe_fault", switch=sw, port_name=p.port)
        metric_rows.append({"switch_id": sw.id, "port_name": p.port, "ts": now, "power_w": p.power_drawn_w,
                            "status": p.detection_status})
    if metric_rows:
        db.execute(pg_insert(PoeMetric).values(metric_rows).on_conflict_do_nothing())
    if summary.budget_w and summary.consumed_w is not None:
        pct = 100 * summary.consumed_w / summary.budget_w
        thr = float(sysset.get(db, "alerts.poe_threshold"))
        if pct >= thr:
            alerts.raise_alert(db, type="high_poe", switch=sw,
                               message=f"PoE on {sw.hostname} at {pct:.0f}% of budget ({summary.consumed_w:.0f}/{summary.budget_w:.0f} W)",
                               details={"pct": round(pct, 1)})
        else:
            alerts.resolve(db, type="high_poe", switch=sw)
    _switch_metric(db, sw, reachable=True, poe_consumed_w=summary.consumed_w, poe_budget_w=summary.budget_w)
    return {"budget": summary.budget_w, "consumed": summary.consumed_w, "ports": len(ports)}


def _vendor(db: Session, mac: str, cache: dict[str, str | None]) -> str | None:
    prefix = mac[:8].upper()
    if prefix not in cache:
        row = db.get(OuiVendor, prefix)
        cache[prefix] = row.vendor if row else None
    return cache[prefix]


def poll_mac(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    entries = drv.get_mac_table()
    _mark_success(db, sw)
    now = utcnow()
    uplinks = set(sw.uplink_ports or [])
    existing = {(e.mac, e.vlan_id): e for e in db.execute(select(MacLearnedEntry).where(
        MacLearnedEntry.switch_id == sw.id)).scalars()}
    first_poll = not existing
    seen = set()
    new = 0
    cache: dict[str, str | None] = {}
    for e in entries:
        key = (e.mac, e.vlan_id)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            # The same MAC already known on this switch under another VLAN (it moved VLAN, or an older reading
            # recorded a wrong VLAN) keeps its first-seen time and is not reported as a new device.
            known_here = [r for (mac, _v), r in existing.items() if mac == e.mac]
            first_seen = min((r.first_seen for r in known_here), default=now)
            row = MacLearnedEntry(switch_id=sw.id, mac=e.mac, vlan_id=e.vlan_id, port_name=e.port,
                                  vendor=_vendor(db, e.mac, cache), first_seen=first_seen, last_seen=now, active=True)
            db.add(row)
            existing[key] = row
            if not first_poll and not known_here and e.port not in uplinks:
                new += 1
                # Fleet-wide: a MAC is "new" only if never seen on any switch before.
                seen_elsewhere = db.execute(select(MacLearnedEntry.id).where(
                    MacLearnedEntry.mac == e.mac, MacLearnedEntry.switch_id != sw.id).limit(1)).first()
                if not seen_elsewhere:
                    alerts.raise_alert(db, type="new_device", switch=sw, port_name=e.port,
                                       message=f"New device {e.mac} on {sw.hostname} port {e.port} (VLAN {e.vlan_id})",
                                       dedup_suffix=e.mac, details={"mac": e.mac, "vlan": e.vlan_id})
        else:
            row.port_name = e.port
            row.last_seen = now
            row.active = True
    for key, row in existing.items():
        if key not in seen and row.active:
            row.active = False
    return {"entries": len(entries), "new": new}


def poll_lldp(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    neighbors = drv.get_lldp_neighbors()
    _mark_success(db, sw)
    now = utcnow()
    by_mac = {s.base_mac: s.id for s in db.execute(select(Switch).where(Switch.base_mac.is_not(None))).scalars()}
    by_name = {s.hostname: s.id for s in db.execute(select(Switch)).scalars()}
    existing = {(n.local_port, n.chassis_id, n.remote_port): n for n in db.execute(select(SwitchNeighbor).where(
        SwitchNeighbor.switch_id == sw.id, SwitchNeighbor.source == "lldp")).scalars()}
    seen = set()
    for n in neighbors:
        key = (n.local_port, n.chassis_id, n.remote_port)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            row = SwitchNeighbor(switch_id=sw.id, local_port=n.local_port, chassis_id=n.chassis_id,
                                 remote_port=n.remote_port, source="lldp", first_seen=now)
            db.add(row)
        row.remote_port_desc, row.system_name = n.remote_port_desc, n.system_name
        row.system_description, row.mgmt_address, row.capabilities = n.system_description, n.mgmt_address, n.capabilities
        row.remote_switch_id = by_mac.get(n.chassis_id) or by_name.get(n.system_name)
        row.last_seen = now
    for key, row in existing.items():
        if key not in seen and now - row.last_seen > timedelta(hours=24):
            db.delete(row)
    return {"neighbors": len(neighbors)}


def sync_inventory(db: Session, sw: Switch, drv: SwitchDriver) -> dict:
    """Identity, capabilities, port configuration and VLAN membership from the device."""
    caps = drv.probe()
    info = drv.get_system()
    _mark_success(db, sw)
    problems = dict((sw.capabilities or {}).get("credential_problems") or {})
    sw.capabilities = {"rest": caps.get("rest"), "snmp": caps.get("snmp"), "ssh": caps.get("ssh"),
                       "resources": caps.get("resources", {}), "errors": caps.get("errors", [])[:20],
                       "probed_at": utcnow().isoformat(), "credential_problems": problems}
    for proto in ("rest", "snmp", "ssh"):
        if caps.get(proto) is True:
            set_credential_problem(sw, proto, None)
        elif caps.get(proto) is False:
            for e in caps.get("errors", []):
                if e.get("protocol") == proto and e.get("code") in CREDENTIAL_ERROR_CODES:
                    set_credential_problem(sw, proto, DriverError(e["code"], e.get("message", ""), protocol=proto))
                    break
    if caps.get("rest_version"):
        sw.rest_api_version = caps["rest_version"]
    if info.hostname:
        sw.hostname = info.hostname
    sw.product_number = info.product_number or sw.product_number
    sw.model_name = info.model_name or sw.model_name
    sw.serial_number = info.serial_number or sw.serial_number
    sw.base_mac = info.base_mac or sw.base_mac
    sw.firmware = info.firmware or sw.firmware
    sw.rom_version = info.rom_version or sw.rom_version
    sw.uptime_seconds = info.uptime_seconds or sw.uptime_seconds
    if info.product_number:
        model = db.execute(select(SwitchModel).where(SwitchModel.product_number == info.product_number)).scalar_one_or_none()
        sw.model_id = model.id if model else None
    ports = drv.get_ports()
    pmap = _port_map(db, sw)
    spec = hwmodels.spec_for(sw.product_number)
    poe_ports = {c.port_name for c in db.execute(select(PoeConfiguration).where(
        PoeConfiguration.switch_id == sw.id)).scalars()}
    for p in ports:
        row = pmap.get(p.name)
        if row is None:
            if p.if_index is None:
                continue
            row = SwitchPort(switch_id=sw.id, if_index=p.if_index, name=p.name, tagged_vlans=[],
                             port_number=hwmodels.port_number(p.name))
            db.add(row)
            pmap[p.name] = row
        if p.if_index is not None:
            row.if_index = p.if_index
        row.description = p.description
        row.admin_up, row.oper_up = p.admin_up, p.oper_up
        row.config_mode, row.trunk_group = p.config_mode, p.trunk_group
        row.speed_mbps, row.duplex = p.speed_mbps, p.duplex
        row.is_uplink = p.name in (sw.uplink_ports or [])
        ptype = hwmodels.port_type(spec, p.name, poe_port=p.name in poe_ports)
        if ptype or not row.port_type:
            row.port_type = ptype
    vlans = drv.get_vlans()
    existing_v = {v.vlan_id: v for v in db.execute(select(SwitchVlan).where(SwitchVlan.switch_id == sw.id)).scalars()}
    for v in vlans:
        row = existing_v.pop(v.vlan_id, None)
        if row is None:
            row = SwitchVlan(switch_id=sw.id, vlan_id=v.vlan_id)
            db.add(row)
        row.name, row.status, row.is_management = v.name, v.status, v.is_management
        if v.is_management:
            sw.mgmt_vlan = v.vlan_id
    for row in existing_v.values():
        db.delete(row)
    try:
        members = drv.get_vlan_memberships()
    except DriverError as exc:
        if exc.code != "unsupported":
            raise
        members = None
    if members is not None:
        db.query(PortVlanMembership).filter(PortVlanMembership.switch_id == sw.id).delete()
        untagged: dict[str, int] = {}
        tagged: dict[str, list[int]] = {}
        for m in members:
            if m.mode == "forbidden":
                continue
            db.add(PortVlanMembership(switch_id=sw.id, port_name=m.port, vlan_id=m.vlan_id, mode=m.mode))
            if m.mode == "untagged":
                untagged[m.port] = m.vlan_id
            else:
                tagged.setdefault(m.port, []).append(m.vlan_id)
        for name, row in pmap.items():
            row.untagged_vlan = untagged.get(name)
            row.tagged_vlans = sorted(tagged.get(name, []))
    return {"ports": len(ports), "vlans": len(vlans), "capabilities": sw.capabilities.get("resources")}


CATEGORIES: dict[str, Callable[[Session, Switch, SwitchDriver], dict]] = {
    "availability": poll_availability,
    "counters": poll_counters,
    "health": poll_health,
    "temperature": poll_temperature,
    "poe": poll_poe,
    "mac": poll_mac,
    "lldp": poll_lldp,
    "inventory": sync_inventory,
}


# ------------------------------------------------------------------ orchestration

def _lock(switch_id: int, category: str) -> Any:
    try:
        import redis

        s = get_settings()
        if s.environment == "test":
            return None
        r = redis.Redis.from_url(s.redis_url, socket_timeout=2)
        lock = r.lock(f"anm:poll:{category}:{switch_id}", timeout=300, blocking=False)
        return lock if lock.acquire(blocking=False) else False
    except Exception:  # noqa: BLE001 - polling continues without locks if Redis is down
        return None


def poll_switch(switch_id: int, category: str) -> dict:
    fn = CATEGORIES[category]
    lock = _lock(switch_id, category)
    if lock is False:
        return {"switch_id": switch_id, "skipped": "previous poll still running"}
    factory = session_factory()
    db = factory()
    try:
        sw = db.get(Switch, switch_id)
        if sw is None or not sw.monitoring_enabled:
            return {"switch_id": switch_id, "skipped": "not monitored"}
        try:
            with driver_for(db, sw, "monitor") as drv:
                result = fn(db, sw, drv)
                if getattr(drv, "ctx", None) is not None and drv.ctx.probed:
                    caps = dict(sw.capabilities or {})
                    res = dict(caps.get("resources", {}))
                    res.update({k: v for k, v in drv.ctx.probed.items() if v is False})
                    caps["resources"] = res
                    sw.capabilities = caps
            db.commit()
            return {"switch_id": switch_id, "ok": True, **result}
        except DriverError as exc:
            db.rollback()
            sw = db.get(Switch, switch_id)
            assert sw is not None
            _mark_failure(db, sw, exc)
            db.commit()
            return {"switch_id": switch_id, "ok": False, "error": exc.to_dict()}
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("poll %s failed for switch %s", category, switch_id)
        return {"switch_id": switch_id, "ok": False, "error": {"code": "internal", "message": str(exc)[:200]}}
    finally:
        db.close()
        if lock:
            try:
                lock.release()
            except Exception:  # noqa: BLE001 - lock may have expired; it is released by Redis TTL
                log.debug("poll lock release failed", exc_info=True)


def run_category(category: str, switch_ids: list[int] | None = None) -> dict:
    if category not in CATEGORIES:
        raise ValueError(category)
    factory = session_factory()
    with factory() as db:
        q = select(Switch.id).where(Switch.monitoring_enabled.is_(True))
        if switch_ids:
            q = q.where(Switch.id.in_(switch_ids))
        ids = list(db.execute(q).scalars())
    started = time.monotonic()
    workers = max(1, min(get_settings().poll_concurrency, len(ids) or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"poll-{category}") as pool:
        results = list(pool.map(lambda i: poll_switch(i, category), ids))
    duration = int((time.monotonic() - started) * 1000)
    failed = [r for r in results if r.get("ok") is False]
    with factory() as db:
        job = db.execute(select(PollingJob).where(PollingJob.category == category)).scalar_one_or_none()
        if job:
            job.last_run_at = utcnow()
            job.last_duration_ms = duration
            job.switches_polled = len(results)
            job.switches_failed = len(failed)
            job.last_status = "ok" if not failed else ("partial" if len(failed) < len(results) else "failed")
            job.last_error = "; ".join(f"#{r['switch_id']}: {r['error']['message']}" for r in failed[:5])[:2000]
            db.commit()
    return {"category": category, "switches": len(results), "failed": len(failed), "duration_ms": duration}
