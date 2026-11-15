"""Simulated SNMPv3 agent answering from simulator state (in-memory, no network)."""

from __future__ import annotations

from typing import Any

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.base import DriverError
from app.drivers.simulator import state as st


def _oid_key(oid: str) -> tuple[int, ...]:
    return tuple(int(x) for x in oid.split("."))


class SimSnmpTransport:
    def __init__(self, ip: str, username: str, auth_password: str, priv_password: str):
        self.ip = ip
        self._valid = (username == "sim-snmp" and auth_password == "sim-auth-passphrase"  # noqa: S105
                       and priv_password == "sim-priv-passphrase")  # noqa: S105

    def _table(self) -> dict[str, Any]:
        sw = st.store.get(self.ip)
        if sw is None or sw.offline:
            raise DriverError("timeout", "SNMP request timed out", protocol="snmp", retriable=True)
        if not self._valid:
            raise DriverError("auth_failed", "SNMPv3 authentication failed (wrong digest)", protocol="snmp")
        t: dict[str, Any] = {
            o.SYS_DESCR: f"{sw.profile.description}, revision {sw.profile.firmware}, ROM {sw.profile.rom} (/ws/swbuildm/rel)",
            o.SYS_OBJECT_ID: "1.3.6.1.4.1.11.2.3.7.11.181.11",
            o.SYS_UPTIME: sw.uptime() * 100,
            o.SYS_NAME: sw.hostname,
            o.SYS_LOCATION: sw.location,
            o.SYS_CONTACT: "noc@example.invalid",
            o.HP_CPU: sw.cpu(),
            f"{o.HP_MEM_TOTAL}.1": sw.mem_total(),
            f"{o.HP_MEM_FREE}.1": sw.mem_free(),
            f"{o.PETH_MAIN_POWER}.1": int(sw.profile.poe_budget_w),
            f"{o.PETH_MAIN_STATUS}.1": 1,
            f"{o.PETH_MAIN_CONSUMPTION}.1": int(round(sw.poe_consumed())),
            # One celsius sensor (type 8, scale 9=units). Real 2540 availability is unverified.
            f"{o.ENT_SENSOR_TYPE}.1": 8,
            f"{o.ENT_SENSOR_SCALE}.1": 9,
            f"{o.ENT_SENSOR_VALUE}.1": int(sw.temperature()),
        }
        for name, p in sw.ports.items():
            i = sw.if_index(name)
            c = sw.counters(p)
            up = sw.oper_up(p)
            t[f"{o.IF_DESCR}.{i}"] = name
            t[f"{o.IF_TYPE}.{i}"] = 6
            t[f"{o.IF_SPEED}.{i}"] = min(p.speed * 1_000_000, 4294967295) if up else 0
            t[f"{o.IF_ADMIN}.{i}"] = 1 if p.enabled else 2
            t[f"{o.IF_OPER}.{i}"] = 1 if up else 2
            t[f"{o.IF_IN_DISCARDS}.{i}"] = c["in_disc"]
            t[f"{o.IF_IN_ERRORS}.{i}"] = c["in_err"]
            t[f"{o.IF_OUT_DISCARDS}.{i}"] = c["out_disc"]
            t[f"{o.IF_OUT_ERRORS}.{i}"] = c["out_err"]
            t[f"{o.IF_NAME}.{i}"] = name
            t[f"{o.IF_HC_IN_OCTETS}.{i}"] = c["in"]
            t[f"{o.IF_HC_OUT_OCTETS}.{i}"] = c["out"]
            t[f"{o.IF_HIGH_SPEED}.{i}"] = p.speed if up else 0
            t[f"{o.IF_ALIAS}.{i}"] = p.description
            t[f"{o.DOT3_DUPLEX}.{i}"] = (2 if p.config_mode.endswith("half") else 3) if up else 1
            t[f"{o.DOT1D_BASEPORT_IFINDEX}.{i}"] = i
        # VLAN interfaces (ifType 136) must be filtered out by the parser.
        # Like AOS-Switch, the FDB index (dot1qFdbId) is an internal counter, not the VLAN ID.
        fdb_ids = {vid: k for k, vid in enumerate(sorted(sw.vlans), start=1)}
        for vid, vname in sw.vlans.items():
            t[f"{o.IF_NAME}.{1000 + vid}"] = f"VLAN{vid}"
            t[f"{o.IF_TYPE}.{1000 + vid}"] = 136
            t[f"{o.DOT1Q_VLAN_NAME}.{vid}"] = vname
            t[f"{o.DOT1Q_VLAN_FDB_ID}.0.{vid}"] = fdb_ids[vid]
        # Q-BRIDGE static membership bitmaps (bridge port = ifIndex on AOS-Switch).
        width = (max((sw.if_index(n) for n in sw.ports), default=0) + 7) // 8

        def bitmap(names: list[str]) -> bytes:
            b = bytearray(width)
            for n in names:
                i = sw.if_index(n) - 1
                b[i // 8] |= 0x80 >> (i % 8)
            return bytes(b)

        for vid in sw.vlans:
            unt = [n for n, v in sw.untagged.items() if v == vid]
            tag = [n for n, vs in sw.tagged.items() if vid in vs]
            t[f"{o.DOT1Q_VLAN_STATIC_EGRESS}.{vid}"] = bitmap(unt + tag)
            t[f"{o.DOT1Q_VLAN_STATIC_UNTAGGED}.{vid}"] = bitmap(unt)
        # POWER-ETHERNET-MIB per-port table (group 1, port index = ifIndex) and HP per-port milliwatts.
        for name, p in sw.ports.items():
            if not sw.is_poe_port(name):
                continue
            idx = f"1.{sw.if_index(name)}"
            status = sw.poe_status(p)
            t[f"{o.PETH_PORT_ADMIN}.{idx}"] = 1 if p.poe_enabled else 2
            t[f"{o.PETH_PORT_DETECTION}.{idx}"] = {"PPDS_DISABLED": 1, "PPDS_SEARCHING": 2, "PPDS_DELIVERING": 3,
                                                   "PPDS_FAULT": 4}.get(status, 6)
            t[f"{o.PETH_PORT_PRIORITY}.{idx}"] = {"critical": 1, "high": 2, "low": 3}[p.poe_priority]
            t[f"{o.PETH_PORT_CLASS}.{idx}"] = int(p.poe_class) + 1 if p.poe_class else 1
            t[f"{o.HP_POE_PORT_POWER_MW}.{idx}"] = int(round(sw.poe_drawn(p) * 1000))
            t[f"{o.HP_POE_PORT_ALLOCATE_BY}.{idx}"] = {"usage": 1, "class": 2, "value": 3}[p.poe_alloc]
        for m in sw.macs:
            if sw.oper_up(sw.ports[m["port"]]) and m["vlan"] in fdb_ids:
                octs = ".".join(str(int(x, 16)) for x in m["mac"].split(":"))
                t[f"{o.DOT1Q_FDB_PORT}.{fdb_ids[m['vlan']]}.{octs}"] = sw.if_index(m["port"])
        for k, n in enumerate(sw.lldp, start=1):
            if sw.oper_up(sw.ports[n["local_port"]]):
                idx = f"0.{n['local_port']}.{k}"
                t[f"{o.LLDP_REM_CHASSIS_ID}.{idx}"] = n["chassis_id"]
                t[f"{o.LLDP_REM_PORT_ID}.{idx}"] = n["port_id"]
                t[f"{o.LLDP_REM_PORT_DESC}.{idx}"] = n["port_description"]
                t[f"{o.LLDP_REM_SYS_NAME}.{idx}"] = n["system_name"]
                t[f"{o.LLDP_REM_SYS_DESC}.{idx}"] = n["system_description"]
        return t

    def get(self, oids: list[str]) -> dict[str, Any]:
        t = self._table()
        return {oid: t.get(oid) for oid in oids}

    def walk(self, oid: str) -> list[tuple[str, Any]]:
        t = self._table()
        prefix = oid + "."
        rows = [(k, v) for k, v in t.items() if k.startswith(prefix)]
        return sorted(rows, key=lambda kv: _oid_key(kv[0]))
