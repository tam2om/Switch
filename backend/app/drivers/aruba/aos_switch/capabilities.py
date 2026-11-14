"""Capability registry for Aruba AOS-Switch firmware.

Each capability records which protocol/resource implements it and the evidence level:

* "documented"  - described in the HPE/Aruba AOS-Switch 16.11 REST API / MIB / CLI reference, NOT yet confirmed
                  on a physical Aruba 2540 running YC.16.11.0018 by this project.
* "verified"    - confirmed against a physical device (set only by the hardware validation harness, see
                  docs/HARDWARE_VALIDATION.md). Nothing is "verified" in the shipped registry.
* "unsupported" - known not to be available; the operation is refused or a validated fallback is used.

At runtime the driver additionally probes each REST resource on every switch and stores the result in
switches.capabilities so operations are only attempted where the device answered.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Capability:
    key: str
    protocol: str  # rest | snmp | ssh
    resource: str  # REST path, OID or CLI command
    evidence: str = "documented"
    write: bool = False
    fallback: str | None = None  # capability key used when this one is unavailable on the device
    notes: str = ""


# REST API version used for AOS-Switch 16.11. The driver negotiates via GET /rest/version and uses the highest
# version listed that is <= MAX_REST_VERSION.
MAX_REST_VERSION = 7
MIN_REST_VERSION = 3

AOS_S_16_11: dict[str, Capability] = {c.key: c for c in [
    Capability("rest.login", "rest", "POST /login-sessions"),
    Capability("system.read", "rest", "GET /system/status", fallback="snmp.system"),
    Capability("snmp.system", "snmp", "SNMPv2-MIB::system (1.3.6.1.2.1.1)"),
    Capability("health.cpu", "snmp", "STATISTICS-MIB::hpSwitchCpuStat 1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"),
    Capability("health.memory", "snmp", "NETSWITCH-MIB::hpLocalMemTotalBytes/FreeBytes 1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1"),
    Capability("health.temperature", "snmp", "ENTITY-SENSOR-MIB::entPhySensorValue (type celsius)",
               notes="2540 may not expose temperature sensors via ENTITY-SENSOR-MIB; shown as unavailable if absent"),
    Capability("ports.read", "rest", "GET /ports", fallback="snmp.ifmib"),
    Capability("snmp.ifmib", "snmp", "IF-MIB ifTable/ifXTable"),
    Capability("ports.counters", "snmp", "IF-MIB ifHCInOctets/ifHCOutOctets/ifInErrors/..."),
    Capability("ports.admin", "rest", "PUT /ports/{id} is_port_enabled", write=True, fallback="cli.interface"),
    Capability("ports.description", "rest", "PUT /ports/{id} name", write=True, fallback="cli.interface"),
    Capability("ports.speed_duplex", "rest", "PUT /ports/{id} config_mode", write=True, fallback="cli.interface"),
    Capability("vlans.read", "rest", "GET /vlans", fallback="snmp.qbridge"),
    Capability("snmp.qbridge", "snmp", "Q-BRIDGE-MIB dot1qVlanStaticTable"),
    Capability("vlans.write", "rest", "POST/PUT/DELETE /vlans", write=True, fallback="cli.vlan"),
    Capability("vlan_ports.read", "rest", "GET /vlans-ports"),
    Capability("vlan_ports.write", "rest", "POST/DELETE /vlans-ports", write=True, fallback="cli.vlan"),
    Capability("poe.read", "rest", "GET /poe/ports"),
    Capability("poe.stats", "rest", "GET /poe/ports/stats"),
    Capability("poe.summary", "snmp", "POWER-ETHERNET-MIB pethMainPseTable 1.3.6.1.2.1.105.1.3.1.1"),
    Capability("poe.write", "rest", "PUT /poe/ports/{id}", write=True, fallback="cli.interface"),
    Capability("poe.restart", "ssh", "interface <p> no power-over-ethernet ; interface <p> power-over-ethernet",
               write=True, notes="Implemented as disable/enable of PoE on the port; disconnects the powered device"),
    Capability("mac.read", "rest", "GET /mac-table", fallback="snmp.fdb"),
    Capability("snmp.fdb", "snmp", "Q-BRIDGE-MIB dot1qTpFdbPort"),
    Capability("lldp.read", "rest", "GET /lldp/remote-device", fallback="snmp.lldp"),
    Capability("snmp.lldp", "snmp", "LLDP-MIB lldpRemTable 1.0.8802.1.1.2.1.4.1"),
    Capability("config.running", "rest", "POST /cli {cmd: 'show running-config'}", fallback="ssh.show_run"),
    Capability("ssh.show_run", "ssh", "show running-config"),
    Capability("config.startup", "ssh", "show config"),
    Capability("config.upload_startup", "ssh", "SFTP put /cfg/startup-config", write=True,
               notes="Requires 'ip ssh filetransfer' on the switch; activation requires a reload"),
    Capability("config.write_memory", "rest", "POST /cli {cmd: 'write memory'}", write=True, fallback="ssh.write_mem"),
    Capability("ssh.write_mem", "ssh", "write memory", write=True),
    Capability("cli.interface", "ssh", "interface <p> (enable|disable|name|speed-duplex|power-over-ethernet)",
               write=True),
    Capability("cli.vlan", "ssh", "vlan <id> (name|tagged|untagged|no)", write=True),
    Capability("cli.security", "ssh", "allow-listed security commands (see cli_commands.py)", write=True),
]}

REGISTRY: dict[tuple[str, str], dict[str, Capability]] = {
    ("aos-switch", "16.11"): AOS_S_16_11,
}

SUPPORTED_PRODUCTS = {
    # Product numbers are matched only after the device reports them; nothing is assumed from inventory.
    "JL356A": "Aruba 2540 24G PoE+ 4SFP+ Switch",
    "JL354A": "Aruba 2540 24G 4SFP+ Switch",
    "JL357A": "Aruba 2540 48G PoE+ 4SFP+ Switch",
    "JL355A": "Aruba 2540 48G 4SFP+ Switch",
}


def firmware_train(firmware: str | None) -> str | None:
    """'YC.16.11.0018' -> '16.11'."""
    if not firmware:
        return None
    parts = firmware.split(".")
    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
        return f"{parts[1]}.{parts[2]}"
    return None


def capabilities_for(firmware: str | None, family: str = "aos-switch") -> dict[str, Capability]:
    train = firmware_train(firmware) or "16.11"
    return REGISTRY.get((family, train), AOS_S_16_11)


def registry_matrix() -> list[dict]:
    rows = []
    for (family, train), caps in REGISTRY.items():
        for c in caps.values():
            rows.append({"family": family, "firmware": train, "key": c.key, "protocol": c.protocol,
                         "resource": c.resource, "evidence": c.evidence, "write": c.write, "fallback": c.fallback,
                         "notes": c.notes})
    return rows
