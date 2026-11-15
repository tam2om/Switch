"""Simulator driver: the real AOS-Switch driver wired to in-memory simulated protocol endpoints."""

from __future__ import annotations

from app.drivers.aruba.aos_switch.driver import AosSwitchDriver, DriverContext
from app.drivers.aruba.aos_switch.rest_client import RestClient
from app.drivers.simulator import rest as sim_rest
from app.drivers.simulator.snmp import SimSnmpTransport
from app.drivers.simulator.ssh import SimSshSession
from app.drivers.simulator.state import FIRMWARE


class SimulatorDriver(AosSwitchDriver):
    name = "simulator"
    is_simulated = True


def build(ip: str, *, rest: tuple[str, str] | None, snmp: tuple[str, str, str] | None,
          ssh: tuple[str, str] | None, host_key_trusted: bool, probed: dict | None = None,
          ssh_read_only: bool = False) -> SimulatorDriver:
    from app.drivers.aruba.aos_switch.ssh_client import ReadOnlySshSession

    def ssh_factory():  # type: ignore[no-untyped-def]
        session = SimSshSession(ip, ssh[0], ssh[1], host_key_trusted)
        return ReadOnlySshSession(session) if ssh_read_only else session

    ctx = DriverContext(
        host=ip,
        firmware=FIRMWARE,
        rest_factory=(lambda: RestClient(ip, rest[0], rest[1], transport=sim_rest.transport(ip), max_retries=0))
        if rest else None,
        snmp_factory=(lambda: SimSnmpTransport(ip, *snmp)) if snmp else None,
        ssh_factory=ssh_factory if ssh else None,
        probed=probed if probed is not None else {},
    )
    return SimulatorDriver(ctx)


SIM_CREDENTIALS = {
    "rest": {"username": sim_rest.SIM_USER, "password": sim_rest.SIM_PASSWORD},
    "snmpv3": {"username": "sim-snmp", "auth_password": "sim-auth-passphrase", "priv_password": "sim-priv-passphrase",
               "auth_protocol": "sha", "priv_protocol": "aes"},
    "ssh": {"username": "sim-ssh", "password": "sim-ssh-password"},
}
def _sim_host_key() -> str:
    import base64
    import hashlib

    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + hashlib.sha256(b"anm-simulator-host-key").digest()
    return "ssh-ed25519 " + base64.b64encode(blob).decode()


SIM_HOST_KEY = _sim_host_key()
