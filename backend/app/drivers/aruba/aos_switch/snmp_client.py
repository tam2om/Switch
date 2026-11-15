"""SNMPv3 client (authPriv only) and OID definitions used for monitoring.

The transport is pluggable: PySnmpTransport talks to real devices; the simulator provides an in-memory
transport answering from simulated switch state. Parsing code is shared, so the simulator exercises the same
logic that runs against hardware.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.drivers.base import DriverError

# ---- OIDs (standard MIBs + HP enterprise MIBs used by AOS-Switch) ----
SYS_DESCR = "1.3.6.1.2.1.1.1.0"
SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
SYS_NAME = "1.3.6.1.2.1.1.5.0"
SYS_LOCATION = "1.3.6.1.2.1.1.6.0"

IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
IF_TYPE = "1.3.6.1.2.1.2.2.1.3"
IF_SPEED = "1.3.6.1.2.1.2.2.1.5"
IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
IF_OPER = "1.3.6.1.2.1.2.2.1.8"
IF_IN_DISCARDS = "1.3.6.1.2.1.2.2.1.13"
IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
IF_OUT_DISCARDS = "1.3.6.1.2.1.2.2.1.19"
IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
IF_HC_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"
IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10"
IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"
IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
DOT3_DUPLEX = "1.3.6.1.2.1.10.7.2.1.19"

HP_CPU = "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"
HP_MEM_TOTAL = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5"
HP_MEM_FREE = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6"

ENT_SENSOR_TYPE = "1.3.6.1.2.1.99.1.1.1.1"
ENT_SENSOR_SCALE = "1.3.6.1.2.1.99.1.1.1.2"
ENT_SENSOR_VALUE = "1.3.6.1.2.1.99.1.1.1.4"

PETH_MAIN_POWER = "1.3.6.1.2.1.105.1.3.1.1.2"
PETH_MAIN_STATUS = "1.3.6.1.2.1.105.1.3.1.1.3"
PETH_MAIN_CONSUMPTION = "1.3.6.1.2.1.105.1.3.1.1.4"

DOT1D_BASEPORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
DOT1Q_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"
DOT1Q_VLAN_NAME = "1.3.6.1.2.1.17.7.1.4.3.1.1"
# dot1qVlanFdbId: index dot1qVlanTimeMark.dot1qVlanIndex (the VLAN ID), value dot1qFdbId. The FDB tables are
# indexed by dot1qFdbId, which on AOS-Switch is an internal counter (1..n), NOT the VLAN ID.
DOT1Q_VLAN_FDB_ID = "1.3.6.1.2.1.17.7.1.4.2.1.3"

LLDP_REM_CHASSIS_ID = "1.0.8802.1.1.2.1.4.1.1.5"
LLDP_REM_PORT_ID = "1.0.8802.1.1.2.1.4.1.1.7"
LLDP_REM_PORT_DESC = "1.0.8802.1.1.2.1.4.1.1.8"
LLDP_REM_SYS_NAME = "1.0.8802.1.1.2.1.4.1.1.9"
LLDP_REM_SYS_DESC = "1.0.8802.1.1.2.1.4.1.1.10"


@dataclass
class SnmpV3Credentials:
    username: str
    auth_password: str
    priv_password: str
    auth_protocol: str = "sha"  # sha | sha256
    priv_protocol: str = "aes"  # aes | aes256

    def __post_init__(self) -> None:
        if self.auth_protocol not in ("sha", "sha256", "sha512"):
            raise DriverError("config", "Unsupported SNMPv3 auth protocol (MD5 is not allowed)", protocol="snmp")
        if self.priv_protocol not in ("aes", "aes192", "aes256"):
            raise DriverError("config", "Unsupported SNMPv3 privacy protocol (DES is not allowed)", protocol="snmp")
        if len(self.auth_password) < 8 or len(self.priv_password) < 8:
            raise DriverError("config", "SNMPv3 passphrases must be at least 8 characters", protocol="snmp")


class SnmpTransport(Protocol):
    def get(self, oids: list[str]) -> dict[str, Any]: ...

    def walk(self, oid: str) -> list[tuple[str, Any]]: ...


class PySnmpTransport:
    """SNMPv3 authPriv transport using pysnmp's asyncio API (run synchronously per call)."""

    def __init__(self, host: str, creds: SnmpV3Credentials, *, port: int = 161, timeout: float = 3.0,
                 retries: int = 1):
        self.host = host
        self.port = port
        self.creds = creds
        self.timeout = timeout
        self.retries = retries

    def _auth(self):  # pragma: no cover - requires network
        from pysnmp.hlapi.v3arch import asyncio as h

        auth = {"sha": h.usmHMACSHAAuthProtocol, "sha256": h.usmHMAC192SHA256AuthProtocol,
                "sha512": h.usmHMAC384SHA512AuthProtocol}[self.creds.auth_protocol]
        priv = {"aes": h.usmAesCfb128Protocol, "aes192": h.usmAesCfb192Protocol,
                "aes256": h.usmAesCfb256Protocol}[self.creds.priv_protocol]
        return h.UsmUserData(self.creds.username, self.creds.auth_password, self.creds.priv_password,
                             authProtocol=auth, privProtocol=priv)

    async def _aget(self, oids: list[str]) -> dict[str, Any]:  # pragma: no cover - requires network
        from pysnmp.hlapi.v3arch import asyncio as h

        engine = h.SnmpEngine()
        try:
            target = await h.UdpTransportTarget.create((self.host, self.port), timeout=self.timeout,
                                                       retries=self.retries)
            err_ind, err_status, _idx, binds = await h.get_cmd(
                engine, self._auth(), target, h.ContextData(), *[h.ObjectType(h.ObjectIdentity(o)) for o in oids])
            if err_ind:
                raise DriverError("snmp_error", f"SNMP: {err_ind}", protocol="snmp", retriable=True)
            if err_status:
                raise DriverError("snmp_error", f"SNMP: {err_status.prettyPrint()}", protocol="snmp")
            out: dict[str, Any] = {}
            for name, val in binds:
                out[str(name)] = _convert(val)
            return out
        finally:
            engine.close_dispatcher()

    async def _awalk(self, oid: str) -> list[tuple[str, Any]]:  # pragma: no cover - requires network
        from pysnmp.hlapi.v3arch import asyncio as h

        engine = h.SnmpEngine()
        out: list[tuple[str, Any]] = []
        try:
            target = await h.UdpTransportTarget.create((self.host, self.port), timeout=self.timeout,
                                                       retries=self.retries)
            async for err_ind, err_status, _idx, binds in h.bulk_walk_cmd(
                    engine, self._auth(), target, h.ContextData(), 0, 25, h.ObjectType(h.ObjectIdentity(oid)),
                    lexicographicMode=False):
                if err_ind:
                    raise DriverError("snmp_error", f"SNMP: {err_ind}", protocol="snmp", retriable=True)
                if err_status:
                    raise DriverError("snmp_error", f"SNMP: {err_status.prettyPrint()}", protocol="snmp")
                for name, val in binds:
                    out.append((str(name), _convert(val)))
            return out
        finally:
            engine.close_dispatcher()

    def get(self, oids: list[str]) -> dict[str, Any]:  # pragma: no cover - requires network
        return asyncio.run(self._aget(oids))

    def walk(self, oid: str) -> list[tuple[str, Any]]:  # pragma: no cover - requires network
        return asyncio.run(self._awalk(oid))


def _convert(val: Any) -> Any:  # pragma: no cover - requires pysnmp value types
    cls = val.__class__.__name__
    if cls in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
        return None
    if cls in ("Integer", "Integer32", "Counter32", "Counter64", "Gauge32", "Unsigned32", "TimeTicks"):
        return int(val)
    if cls == "OctetString":
        raw = bytes(val)
        try:
            text = raw.decode()
            if text.isprintable():
                return text
        except UnicodeDecodeError:
            pass
        return raw
    if cls == "ObjectIdentifier":
        return str(val)
    if cls == "IpAddress":
        return ".".join(str(b) for b in bytes(val))
    return val.prettyPrint()


class SnmpClient:
    def __init__(self, transport: SnmpTransport):
        self.t = transport

    def get(self, oids: list[str]) -> dict[str, Any]:
        return self.t.get(oids)

    def table(self, column_oid: str) -> dict[str, Any]:
        """Walk a column and return {index_suffix: value}."""
        prefix = column_oid + "."
        return {oid[len(prefix):]: v for oid, v in self.t.walk(column_oid) if oid.startswith(prefix)}

    def tables(self, columns: Iterable[str]) -> dict[str, dict[str, Any]]:
        return {c: self.table(c) for c in columns}


def format_mac(raw: Any) -> str:
    if isinstance(raw, bytes | bytearray):
        return ":".join(f"{b:02x}" for b in raw)
    s = str(raw).strip().lower().replace("-", "").replace(":", "").replace(".", "").replace(" ", "")
    if s.startswith("0x"):
        s = s[2:]
    if len(s) == 12 and all(c in "0123456789abcdef" for c in s):
        return ":".join(s[i:i + 2] for i in range(0, 12, 2))
    return str(raw)


def mac_from_oid_suffix(suffix: str) -> str:
    return ":".join(f"{int(x):02x}" for x in suffix.split(".")[-6:])
