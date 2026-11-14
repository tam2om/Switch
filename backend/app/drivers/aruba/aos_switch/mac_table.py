from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.base import MacEntry


def parse_rest_mac_table(data: dict) -> list[MacEntry]:
    out = []
    for e in data.get("mac_table_entry_element", []):
        out.append(MacEntry(mac=o.format_mac(e.get("mac_address", "")), vlan_id=int(e.get("vlan_id", 0)),
                            port=str(e.get("port_id"))))
    return out


def snmp_mac_table(snmp: o.SnmpClient) -> list[MacEntry]:
    baseport = {k: int(v) for k, v in snmp.table(o.DOT1D_BASEPORT_IFINDEX).items()}
    names = snmp.table(o.IF_NAME)
    out = []
    for suffix, bport in snmp.table(o.DOT1Q_FDB_PORT).items():
        parts = suffix.split(".")
        if len(parts) != 7 or not bport:
            continue
        ifidx = baseport.get(str(bport), int(bport))
        out.append(MacEntry(mac=o.mac_from_oid_suffix(suffix), vlan_id=int(parts[0]),
                            port=str(names.get(str(ifidx), ifidx))))
    return out
