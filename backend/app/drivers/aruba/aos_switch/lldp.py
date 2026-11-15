from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.base import LldpNeighbor


def parse_rest_lldp(data: dict) -> list[LldpNeighbor]:
    out = []
    for e in data.get("lldp_remote_device_element", []):
        mgmt = None
        addrs = e.get("remote_management_address") or []
        if addrs:
            mgmt = addrs[0].get("address")
        out.append(LldpNeighbor(
            local_port=str(e.get("local_port")), chassis_id=o.format_mac(e.get("chassis_id", "")),
            remote_port=str(e.get("port_id", "")), remote_port_desc=e.get("port_description", ""),
            system_name=e.get("system_name", ""), system_description=e.get("system_description", ""),
            mgmt_address=mgmt, capabilities=[c for c in (e.get("capabilities_enabled") or {}) if
                                             (e.get("capabilities_enabled") or {}).get(c)]
            if isinstance(e.get("capabilities_enabled"), dict) else list(e.get("capabilities_enabled") or []),
        ))
    return out


def snmp_lldp(snmp: o.SnmpClient) -> list[LldpNeighbor]:
    cols = snmp.tables([o.LLDP_REM_CHASSIS_ID, o.LLDP_REM_PORT_ID, o.LLDP_REM_PORT_DESC, o.LLDP_REM_SYS_NAME,
                        o.LLDP_REM_SYS_DESC])
    out = []
    for idx, name in cols[o.LLDP_REM_SYS_NAME].items():
        parts = idx.split(".")  # timeMark.localPortNum.remIndex
        if len(parts) < 3:
            continue
        out.append(LldpNeighbor(local_port=parts[1], chassis_id=o.format_mac(cols[o.LLDP_REM_CHASSIS_ID].get(idx, "")),
                                remote_port=str(cols[o.LLDP_REM_PORT_ID].get(idx, "")),
                                remote_port_desc=str(cols[o.LLDP_REM_PORT_DESC].get(idx, "")),
                                system_name=str(name), system_description=str(cols[o.LLDP_REM_SYS_DESC].get(idx, ""))))
    return out
