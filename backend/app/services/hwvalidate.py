"""Read-only hardware validation harness.

Runs every read path of the driver against one switch and records what the device actually answered, so that the
capability registry can be confirmed on real hardware (docs/HARDWARE_VALIDATION.md). It never changes the switch:
only probe() and get_* methods are called, with the monitoring (read-only) credentials.

The report records whether the target is simulated. Evidence from a simulated switch is never valid as hardware
evidence; it only shows the harness works.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.drivers.aruba.aos_switch.capabilities import SUPPORTED_PRODUCTS, capabilities_for, firmware_train
from app.drivers.base import DriverError, SwitchDriver
from app.models import HardwareValidation, Switch, SwitchModel
from app.services import audit

# Read checks: (name, capability keys it exercises, call, summary of the result)
_CHECKS: list[tuple[str, list[str], Callable[[SwitchDriver], Any], Callable[[Any], dict]]] = [
    ("system", ["system.read", "snmp.system"], lambda d: d.get_system(),
     lambda r: {"hostname": r.hostname, "product": r.product_number, "model": r.model_name, "firmware": r.firmware}),
    ("health", ["health.cpu", "health.memory", "health.temperature"], lambda d: d.get_health(True),
     lambda r: {"cpu_pct": r.cpu_pct, "mem_pct": r.mem_pct, "temperature_c": r.temperature_c}),
    ("ports", ["ports.read", "snmp.ifmib"], lambda d: d.get_ports(), lambda r: {"count": len(r)}),
    ("port_counters", ["ports.counters"], lambda d: d.get_port_counters(), lambda r: {"count": len(r)}),
    ("vlans", ["vlans.read", "snmp.qbridge"], lambda d: d.get_vlans(), lambda r: {"count": len(r)}),
    ("vlan_memberships", ["vlan_ports.read", "snmp.vlan_ports"], lambda d: d.get_vlan_memberships(),
     lambda r: {"count": len(r), "sample": [asdict(m) for m in r[:8]]}),
    ("poe_ports", ["poe.read", "poe.stats", "snmp.poe_ports"], lambda d: d.get_poe_ports(),
     lambda r: {"count": len(r), "with_watts": sum(1 for p in r if p.power_drawn_w is not None),
                "sample": [asdict(p) for p in r[:8]]}),
    ("poe_summary", ["poe.summary"], lambda d: d.get_poe_summary(),
     lambda r: {"budget_w": r.budget_w, "consumed_w": r.consumed_w, "oper_status": r.oper_status}),
    ("mac_table", ["mac.read", "snmp.fdb"], lambda d: d.get_mac_table(), lambda r: {"count": len(r)}),
    ("lldp", ["lldp.read", "snmp.lldp"], lambda d: d.get_lldp_neighbors(), lambda r: {"count": len(r)}),
    ("running_config", ["config.running", "ssh.show_run"], lambda d: d.get_running_config(),
     lambda r: {"bytes": len(r.text.encode()), "source": r.source}),
    ("startup_config", ["config.startup"], lambda d: d.get_startup_config(),
     lambda r: {"bytes": len(r.text.encode()), "source": r.source}),
]


def run(driver: SwitchDriver, sw: Switch) -> dict:
    report: dict[str, Any] = {
        "generated_at": utcnow().isoformat(),
        "switch": {"id": sw.id, "hostname": sw.hostname, "mgmt_ip": sw.mgmt_ip, "inventory_firmware": sw.firmware},
        "simulated": bool(sw.is_simulated or sw.driver == "simulator"),
        "valid_as_hardware_evidence": False,
        "read_only": True,
        "checks": [],
    }
    t0 = time.monotonic()
    try:
        report["probe"] = driver.probe()
    except DriverError as exc:
        report["probe"] = {"error": exc.to_dict()}
    for name, caps, call, summarize in _CHECKS:
        started = time.monotonic()
        row: dict[str, Any] = {"check": name, "capabilities": caps}
        try:
            result = call(driver)
            row["ok"] = True
            row["result"] = summarize(result)
        except DriverError as exc:
            row["ok"] = False
            row["error"] = exc.to_dict()
        except Exception as exc:  # noqa: BLE001 - a harness must report, not crash
            row["ok"] = False
            row["error"] = {"code": "unexpected", "message": exc.__class__.__name__}
        row["seconds"] = round(time.monotonic() - started, 3)
        report["checks"].append(row)
    report["seconds"] = round(time.monotonic() - t0, 3)

    system = next((c for c in report["checks"] if c["check"] == "system" and c["ok"]), None)
    reported = (system or {}).get("result", {})
    product, firmware = reported.get("product"), reported.get("firmware")
    report["device"] = {
        "product": product,
        "product_supported": product in SUPPORTED_PRODUCTS if product else None,
        "firmware": firmware,
        "registry": sorted(capabilities_for(firmware).keys()),
    }
    report["summary"] = {
        "passed": sum(1 for c in report["checks"] if c["ok"]),
        "failed": sum(1 for c in report["checks"] if not c["ok"]),
    }
    # Only a physical switch that identified itself can provide evidence; a person still has to review it.
    report["valid_as_hardware_evidence"] = not report["simulated"] and bool(product and firmware)
    return report


def record_evidence(db: Session, sw: Switch, report: dict) -> HardwareValidation | None:
    """Store a report from a physical switch and update the model's evidence for that firmware train.
    Simulated switches and reports where the device did not identify itself are never stored as evidence."""
    if not report.get("valid_as_hardware_evidence"):
        return None
    product, firmware = report["device"]["product"], report["device"]["firmware"]
    row = HardwareValidation(switch_id=sw.id, hostname=sw.hostname, product_number=product, firmware=firmware,
                             passed=report["summary"]["passed"], failed=report["summary"]["failed"], report=report)
    db.add(row)
    db.flush()
    report["validation_id"] = row.id
    model = db.execute(select(SwitchModel).where(SwitchModel.product_number == product)).scalar_one_or_none()
    if model is not None:
        evidence = dict(model.hardware_evidence or {})
        train = firmware_train(firmware) or firmware
        evidence[train] = {"at": row.created_at.isoformat(), "switch_id": sw.id, "hostname": sw.hostname,
                           "firmware": firmware, "passed": row.passed, "failed": row.failed, "validation_id": row.id}
        model.hardware_evidence = evidence
    audit.record(db, action="hardware.validate", category="operational", actor_name="cli", target_type="switch",
                 target_id=sw.id, switch_id=sw.id, result="success" if row.failed == 0 else "failure",
                 details={"product": product, "firmware": firmware, "passed": row.passed, "failed": row.failed,
                          "validation_id": row.id})
    return row


def run_for_switch(db: Session, switch_id: int, *, record: bool = True) -> dict:
    from app.services.devices import driver_for

    sw = db.get(Switch, switch_id)
    if sw is None:
        raise ValueError(f"switch {switch_id} not found")
    driver = driver_for(db, sw, "monitor")
    try:
        report = run(driver, sw)
    finally:
        driver.close()
    if record:
        record_evidence(db, sw, report)
        db.commit()
    return report
