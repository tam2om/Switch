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
    return [VlanInfo(vlan_id=int(idx), name=str(name)) for idx, name in snmp.table(o.DOT1Q_VLAN_NAME).items()
            if idx.isdigit()]
