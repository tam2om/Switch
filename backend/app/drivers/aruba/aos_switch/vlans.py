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


def _bridge_port_names(snmp: o.SnmpClient) -> dict[int, str]:
    """Bridge port number -> interface name, through dot1dBasePortIfIndex and ifName."""
    names = snmp.table(o.IF_NAME)
    baseport = snmp.table(o.DOT1D_BASEPORT_IFINDEX)
    if baseport:
        return {int(bp): str(names.get(str(ifidx), ifidx)) for bp, ifidx in baseport.items() if bp.isdigit()}
    # No bridge port table: AOS-Switch numbers bridge ports like ifIndex.
    return {int(i): str(n) for i, n in names.items() if i.isdigit()}


def snmp_vlan_memberships(snmp: o.SnmpClient) -> list[VlanMembership]:
    """Configured (static) membership from Q-BRIDGE-MIB; the current table is used if the static one is empty."""
    egress = {int(k): v for k, v in snmp.table(o.DOT1Q_VLAN_STATIC_EGRESS).items() if k.isdigit()}
    untagged = {int(k): v for k, v in snmp.table(o.DOT1Q_VLAN_STATIC_UNTAGGED).items() if k.isdigit()}
    if not egress:
        def by_vid(table: dict) -> dict[int, object]:
            return {int(k.split(".")[-1]): v for k, v in table.items() if k.split(".")[-1].isdigit()}

        egress = by_vid(snmp.table(o.DOT1Q_VLAN_CURRENT_EGRESS))
        untagged = by_vid(snmp.table(o.DOT1Q_VLAN_CURRENT_UNTAGGED))
    if not egress:
        return []
    ports = _bridge_port_names(snmp)
    out = []
    for vid in sorted(egress):
        unt = o.portlist(untagged.get(vid))
        for bp in sorted(o.portlist(egress[vid]) | unt):
            name = ports.get(bp)
            if name is None:
                continue
            out.append(VlanMembership(vlan_id=vid, port=name, mode="untagged" if bp in unt else "tagged"))
    return out
