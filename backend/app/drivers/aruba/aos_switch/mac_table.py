from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.base import MacEntry


def parse_rest_mac_table(data: dict) -> list[MacEntry]:
    out = []
    for e in data.get("mac_table_entry_element", []):
        out.append(MacEntry(mac=o.format_mac(e.get("mac_address", "")), vlan_id=int(e.get("vlan_id", 0)),
                            port=str(e.get("port_id"))))
    return out


def fdb_to_vlan(snmp: o.SnmpClient) -> dict[int, int]:
    """Map dot1qFdbId -> 802.1Q VLAN ID from dot1qVlanCurrentTable (index timeMark.vlanId, value fdbId)."""
    out: dict[int, int] = {}
    for suffix, fdb in snmp.table(o.DOT1Q_VLAN_FDB_ID).items():
        parts = suffix.split(".")
        if len(parts) == 2 and parts[1].isdigit() and fdb is not None:
            out[int(fdb)] = int(parts[1])
    return out


def snmp_mac_table(snmp: o.SnmpClient) -> list[MacEntry]:
    baseport = {k: int(v) for k, v in snmp.table(o.DOT1D_BASEPORT_IFINDEX).items()}
    names = snmp.table(o.IF_NAME)
    fdb_vlan = fdb_to_vlan(snmp)
    out = []
    for suffix, bport in snmp.table(o.DOT1Q_FDB_PORT).items():
        parts = suffix.split(".")
        if len(parts) != 7 or not bport:
            continue
        fdb_id = int(parts[0])
        ifidx = baseport.get(str(bport), int(bport))
        # Without a mapping the device uses shared/independent learning where FdbId equals the VLAN ID.
        out.append(MacEntry(mac=o.mac_from_oid_suffix(suffix), vlan_id=fdb_vlan.get(fdb_id, fdb_id),
                            port=str(names.get(str(ifidx), ifidx))))
    return out
