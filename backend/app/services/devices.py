"""Build a driver for a switch from inventory + encrypted credentials."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.drivers.aruba.aos_switch.driver import AosSwitchDriver, DriverContext
from app.drivers.aruba.aos_switch.rest_client import RestClient
from app.drivers.aruba.aos_switch.snmp_client import PySnmpTransport, SnmpV3Credentials
from app.drivers.base import DriverError, SwitchDriver
from app.models import Switch
from app.services import credentials


def driver_for(db: Session, sw: Switch, purpose: str = "monitor") -> SwitchDriver:
    """purpose='monitor' uses read-only credentials; purpose='config' uses configuration credentials for REST/SSH
    (SNMP always uses the monitoring credential: the application never writes via SNMP)."""
    s = get_settings()
    rest = credentials.resolve(db, sw.id, "rest", purpose) if sw.protocols.get("rest", True) else None
    snmp = credentials.resolve(db, sw.id, "snmpv3", "monitor") if sw.protocols.get("snmp", True) else None
    ssh = credentials.resolve(db, sw.id, "ssh", purpose) if sw.protocols.get("ssh", True) else None
    # Without a monitoring SSH account, reads that need SSH (show running-config for backups) may use the
    # configuration account, but only through a session that refuses every configuration command.
    ssh_read_only = False
    if ssh is None and purpose == "monitor" and sw.protocols.get("ssh", True):
        ssh = credentials.resolve(db, sw.id, "ssh", "config")
        ssh_read_only = ssh is not None
    probed = dict((sw.capabilities or {}).get("resources", {}))

    if sw.driver == "simulator" or sw.is_simulated:
        if not s.simulator_enabled and s.environment != "test":
            raise DriverError("simulator_disabled", "Simulator mode is disabled on this installation")
        from app.drivers.simulator import driver as sim

        return sim.build(
            sw.mgmt_ip,
            rest=(rest[0], rest[1]["password"]) if rest else None,
            snmp=(snmp[0], snmp[1]["auth_password"], snmp[1]["priv_password"]) if snmp else None,
            ssh=(ssh[0], ssh[1]["password"]) if ssh else None,
            ssh_read_only=ssh_read_only,
            host_key_trusted=sw.ssh_host_key_trusted,
            probed=probed,
        )

    if sw.driver != "aruba_aos_s":
        raise DriverError("unknown_driver", f"No driver registered for '{sw.driver}'")

    verify: bool | str = s.rest_ca_bundle or s.rest_verify_tls
    ctx = DriverContext(host=sw.mgmt_ip, firmware=sw.firmware, probed=probed)
    if rest:
        ctx.rest_factory = lambda: RestClient(sw.mgmt_ip, rest[0], rest[1]["password"], timeout=s.device_timeout_seconds,
                                              verify=verify, max_retries=s.device_max_retries,
                                              api_version=sw.rest_api_version)
    if snmp:
        creds = SnmpV3Credentials(username=snmp[0], auth_password=snmp[1]["auth_password"],
                                  priv_password=snmp[1]["priv_password"],
                                  auth_protocol=snmp[2].get("auth_protocol", "sha"),
                                  priv_protocol=snmp[2].get("priv_protocol", "aes"))
        ctx.snmp_factory = lambda: PySnmpTransport(sw.mgmt_ip, creds, timeout=min(s.device_timeout_seconds, 5),
                                                   retries=s.device_max_retries)
    if ssh:
        from app.drivers.aruba.aos_switch.ssh_client import NetmikoSession, ReadOnlySshSession

        key = sw.ssh_host_key if sw.ssh_host_key_trusted else None
        def ssh_factory():  # type: ignore[no-untyped-def]
            session = NetmikoSession(sw.mgmt_ip, ssh[0], ssh[1]["password"], key or "",
                                     port=int(ssh[2].get("port", 22)), timeout=s.device_timeout_seconds)
            return ReadOnlySshSession(session) if ssh_read_only else session

        ctx.ssh_factory = ssh_factory
    return AosSwitchDriver(ctx)
