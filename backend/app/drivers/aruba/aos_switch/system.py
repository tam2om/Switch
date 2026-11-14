"""System identity and health."""

from __future__ import annotations

import re

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.aruba.aos_switch.capabilities import SUPPORTED_PRODUCTS
from app.drivers.base import DriverError, HealthInfo, SystemInfo

_PRODUCT_RE = re.compile(r"\b(J[A-Z]?\d{3,4}[A-Z])\b")
_FW_RE = re.compile(r"\b([A-Z]{2}\.\d{2}\.\d{2}\.\d{4})\b")


def _mac(octets: object) -> str | None:
    if not octets:
        return None
    if isinstance(octets, dict):
        octets = octets.get("octets")
    s = str(octets).lower().replace("-", "").replace(":", "")
    return ":".join(s[i:i + 2] for i in range(0, 12, 2)) if len(s) == 12 else str(octets)


def parse_rest_system(system: dict, status: dict) -> SystemInfo:
    product = status.get("product_model") or ""
    pn = None
    m = _PRODUCT_RE.search(product)
    if m:
        pn = m.group(1)
    return SystemInfo(
        hostname=system.get("name") or status.get("name"),
        product_number=pn,
        model_name=SUPPORTED_PRODUCTS.get(pn or "", product or None),
        serial_number=status.get("serial_number"),
        base_mac=_mac(status.get("base_ethernet_address")),
        firmware=status.get("firmware_version"),
        rom_version=status.get("rom_version") or status.get("boot_rom_version"),
        location=system.get("location"),
        contact=system.get("contact"),
    )


def parse_sys_descr(descr: str | None) -> tuple[str | None, str | None]:
    """'Aruba JL356A 2540-24G-PoE+-4SFP+ Switch, revision YC.16.11.0018, ROM YC.16.01.0002 ...'"""
    if not descr:
        return None, None
    pn = _PRODUCT_RE.search(descr)
    fw = _FW_RE.search(descr)
    return (pn.group(1) if pn else None), (fw.group(1) if fw else None)


def snmp_system(snmp: o.SnmpClient) -> SystemInfo:
    v = snmp.get([o.SYS_DESCR, o.SYS_OBJECT_ID, o.SYS_UPTIME, o.SYS_NAME, o.SYS_LOCATION, o.SYS_CONTACT])
    if all(x is None for x in v.values()):
        raise DriverError("snmp_error", "No SNMP system data returned", protocol="snmp")
    pn, fw = parse_sys_descr(v.get(o.SYS_DESCR))
    up = v.get(o.SYS_UPTIME)
    return SystemInfo(hostname=v.get(o.SYS_NAME), product_number=pn, model_name=SUPPORTED_PRODUCTS.get(pn or ""),
                      firmware=fw, uptime_seconds=int(up) // 100 if up is not None else None,
                      location=v.get(o.SYS_LOCATION), contact=v.get(o.SYS_CONTACT),
                      sys_object_id=v.get(o.SYS_OBJECT_ID), description=v.get(o.SYS_DESCR))


def snmp_health(snmp: o.SnmpClient) -> HealthInfo:
    h = HealthInfo()
    v = snmp.get([o.HP_CPU, o.SYS_UPTIME])
    if v.get(o.HP_CPU) is not None:
        h.cpu_pct = float(v[o.HP_CPU])
    if v.get(o.SYS_UPTIME) is not None:
        h.uptime_seconds = int(v[o.SYS_UPTIME]) // 100
    total = snmp.table(o.HP_MEM_TOTAL)
    free = snmp.table(o.HP_MEM_FREE)
    if total:
        idx = sorted(total)[0]
        t = total.get(idx)
        f = free.get(idx)
        if t:
            h.mem_total_bytes = int(t)
            if f is not None:
                h.mem_free_bytes = int(f)
                h.mem_pct = round(100.0 * (int(t) - int(f)) / int(t), 1)
    # Temperature: ENTITY-SENSOR-MIB, sensor type 8 = celsius. Absent sensors -> None (shown as unavailable).
    types = snmp.table(o.ENT_SENSOR_TYPE)
    if types:
        values = snmp.table(o.ENT_SENSOR_VALUE)
        scales = snmp.table(o.ENT_SENSOR_SCALE)
        temps = []
        for idx, t in types.items():
            if int(t) == 8 and values.get(idx) is not None:
                scale = int(scales.get(idx, 9))  # 9 = units
                factor = 10 ** ((scale - 9) * 3)
                temps.append(float(values[idx]) * factor)
        if temps:
            h.temperature_c = round(max(temps), 1)
    return h
