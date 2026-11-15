"""Interfaces: configuration via REST, status and counters via SNMP IF-MIB."""

from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.aruba.aos_switch.models import default_if_index
from app.drivers.base import PortCounters, PortInfo

# REST config_mode enum <-> CLI speed-duplex keyword.
CONFIG_MODES = {
    "PCM_AUTO": "auto", "PCM_10HDX": "10-half", "PCM_10FDX": "10-full", "PCM_100HDX": "100-half",
    "PCM_100FDX": "100-full", "PCM_1000FDX": "1000-full", "PCM_AUTO_10": "auto-10", "PCM_AUTO_100": "auto-100",
    "PCM_AUTO_1000": "auto-1000", "PCM_AUTO_10_100": "auto-10-100",
}
CONFIG_MODES_REV = {v: k for k, v in CONFIG_MODES.items()}


def port_number(name: str) -> int | None:
    """ifIndex assumed for a port first seen over REST (SNMP supplies the real one when available)."""
    return default_if_index(name)


def parse_rest_ports(data: dict) -> list[PortInfo]:
    out = []
    for p in data.get("port_element", []):
        pid = str(p.get("id"))
        trunk = p.get("trunk_group") or None
        out.append(PortInfo(
            name=pid,
            if_index=port_number(pid),
            description=p.get("name") or "",
            admin_up=p.get("is_port_enabled"),
            oper_up=p.get("is_port_up"),
            config_mode=CONFIG_MODES.get(p.get("config_mode", ""), None),
            trunk_group=trunk,
        ))
    return out


def snmp_ports(snmp: o.SnmpClient) -> list[PortInfo]:
    names = snmp.table(o.IF_NAME)
    admin = snmp.table(o.IF_ADMIN)
    oper = snmp.table(o.IF_OPER)
    alias = snmp.table(o.IF_ALIAS)
    speed = snmp.table(o.IF_HIGH_SPEED)
    iftype = snmp.table(o.IF_TYPE)
    duplex = snmp.table(o.DOT3_DUPLEX)
    out = []
    for idx, name in names.items():
        if not idx.isdigit():
            continue
        # ethernetCsmacd(6) and ieee8023adLag(161) only; skip VLAN and loopback interfaces.
        t = iftype.get(idx)
        if t is not None and int(t) not in (6, 161):
            continue
        d = duplex.get(idx)
        out.append(PortInfo(
            name=str(name), if_index=int(idx), description=str(alias.get(idx) or ""),
            admin_up=(int(admin[idx]) == 1) if idx in admin else None,
            oper_up=(int(oper[idx]) == 1) if idx in oper else None,
            speed_mbps=int(speed[idx]) if speed.get(idx) else None,
            duplex={3: "full", 2: "half"}.get(int(d)) if d is not None else None,
        ))
    return sorted(out, key=lambda p: p.if_index or 0)


def merge_ports(rest: list[PortInfo] | None, snmp: list[PortInfo] | None) -> list[PortInfo]:
    """REST is authoritative for configuration; SNMP for ifIndex, speed, duplex and operational status."""
    if not rest:
        return snmp or []
    by_name = {p.name: p for p in (snmp or [])}
    for p in rest:
        s = by_name.get(p.name)
        if s:
            p.if_index = s.if_index
            p.speed_mbps = s.speed_mbps
            p.duplex = s.duplex
            if s.oper_up is not None:
                p.oper_up = s.oper_up
    return rest


def snmp_counters(snmp: o.SnmpClient) -> list[PortCounters]:
    cols = snmp.tables([o.IF_NAME, o.IF_HC_IN_OCTETS, o.IF_HC_OUT_OCTETS, o.IF_IN_ERRORS, o.IF_OUT_ERRORS,
                        o.IF_IN_DISCARDS, o.IF_OUT_DISCARDS, o.IF_OPER, o.IF_HIGH_SPEED, o.IF_TYPE])
    out = []
    for idx, name in cols[o.IF_NAME].items():
        if not idx.isdigit():
            continue
        t = cols[o.IF_TYPE].get(idx)
        if t is not None and int(t) not in (6, 161):
            continue

        def g(c: str, i: str = idx) -> int | None:
            v = cols[c].get(i)
            return int(v) if v is not None else None

        oper = g(o.IF_OPER)
        out.append(PortCounters(if_index=int(idx), name=str(name), in_octets=g(o.IF_HC_IN_OCTETS),
                                out_octets=g(o.IF_HC_OUT_OCTETS), in_errors=g(o.IF_IN_ERRORS),
                                out_errors=g(o.IF_OUT_ERRORS), in_discards=g(o.IF_IN_DISCARDS),
                                out_discards=g(o.IF_OUT_DISCARDS),
                                oper_up=(oper == 1) if oper is not None else None, speed_mbps=g(o.IF_HIGH_SPEED)))
    return out
