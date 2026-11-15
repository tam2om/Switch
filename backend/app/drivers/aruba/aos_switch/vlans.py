from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.base import VlanInfo, VlanMembership

PORT_MODES = {"POM_UNTAGGED": "untagged", "POM_TAGGED_STATIC": "tagged", "POM_FORBIDDEN": "forbidden"}
PORT_MODES_REV = {"untagged": "POM_UNTAGGED", "tagged": "POM_TAGGED_STATIC"}


def parse_rest_vlans(data: dict) -> list[VlanInfo]:
    return [VlanInfo(vlan_id=int(v["vlan_id"]), name=v.get("name", ""),
                     status={"VS_PORT_BASED": "port_based", "VS_PROTOCOL_BASED": "protocol_based"}.get(
                         v.get("status", ""), str(v.get("status", "")).lower()),
                     is_management=bool(v.get("is_management_vlan")), is_voice=bool(v.get("is_voice_enabled")))
            for v in data.get("vlan_element", [])]


def parse_rest_vlan_ports(data: dict) -> list[VlanMembership]:
    out = []
    for e in data.get("vlan_port_element", []):
        mode = PORT_MODES.get(e.get("port_mode", ""))
        if mode:
            out.append(VlanMembership(vlan_id=int(e["vlan_id"]), port=str(e["port_id"]), mode=mode))
    return out


def snmp_vlans(snmp: o.SnmpClient) -> list[VlanInfo]:
    """Configured VLANs (dot1qVlanStaticTable) plus any VLAN only present in dot1qVlanCurrentTable, so the
    default VLAN 1 is listed even when a device leaves it out of the static table."""
    names = {int(idx): str(name or "") for idx, name in snmp.table(o.DOT1Q_VLAN_NAME).items() if idx.isdigit()}
    for suffix in snmp.table(o.DOT1Q_VLAN_FDB_ID):
        parts = suffix.split(".")
        if len(parts) == 2 and parts[1].isdigit():
            names.setdefault(int(parts[1]), "DEFAULT_VLAN" if parts[1] == "1" else "")
    return [VlanInfo(vlan_id=vid, name=name) for vid, name in sorted(names.items())]
