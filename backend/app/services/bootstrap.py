"""Idempotent reference data: roles, permissions, alert rules, polling schedule, switch models."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_DESCRIPTIONS, ROLE_ORDER, ROLE_PERMISSIONS, P
from app.drivers.aruba.aos_switch.models import MODELS as MODEL_CATALOG
from app.models import AlertRule, Permission, PollingJob, Role, RolePermission, SwitchModel

DEFAULT_ALERT_RULES = [
    ("switch_offline", "Switch offline", "critical", None),
    ("switch_recovered", "Switch recovered", "info", None),
    ("port_down", "Uplink / monitored port down", "major", None),
    ("port_flapping", "Port flapping", "warning", 4),
    ("high_errors", "High interface errors", "warning", 10),
    ("high_cpu", "High CPU", "warning", 85),
    ("high_memory", "High memory", "warning", 90),
    ("high_poe", "High PoE utilisation", "warning", 85),
    ("poe_fault", "PoE fault", "major", None),
    ("new_device", "New device detected", "info", None),
    ("unexpected_config_change", "Unexpected configuration change", "major", None),
    ("config_operation_failed", "Failed configuration operation", "major", None),
]

POLLING = [
    ("availability", 30), ("counters", 60), ("health", 60), ("poe", 60), ("temperature", 300), ("mac", 300),
    ("lldp", 300), ("inventory", 3600),
]

# Port layouts follow the published product specifications (app/drivers/aruba/aos_switch/models.py).
# hardware_verified stays False until confirmed on a physical unit (docs/HARDWARE_COMPATIBILITY.md).


def sync_reference_data(db: Session) -> None:
    perms = {p.code: p for p in db.execute(select(Permission)).scalars()}
    for perm in P:
        if perm.value not in perms:
            obj = Permission(code=perm.value, description=perm.name.replace("_", " ").title())
            db.add(obj)
            perms[perm.value] = obj
    db.flush()
    roles = {r.name: r for r in db.execute(select(Role)).scalars()}
    for rank, role in enumerate(ROLE_ORDER):
        if role.value not in roles:
            r = Role(name=role.value, description=ROLE_DESCRIPTIONS[role], is_system=True, rank=rank)
            db.add(r)
            roles[role.value] = r
    db.flush()
    existing = {(rp.role_id, rp.permission_id) for rp in db.execute(select(RolePermission)).scalars()}
    wanted = set()
    for role, plist in ROLE_PERMISSIONS.items():
        for perm in plist:
            wanted.add((roles[role.value].id, perms[perm.value].id))
    for pair in wanted - existing:
        db.add(RolePermission(role_id=pair[0], permission_id=pair[1]))
    for pair in existing - wanted:
        db.query(RolePermission).filter_by(role_id=pair[0], permission_id=pair[1]).delete()

    rules = {r.type for r in db.execute(select(AlertRule)).scalars()}
    for typ, name, sev, thr in DEFAULT_ALERT_RULES:
        if typ not in rules:
            db.add(AlertRule(type=typ, name=name, severity=sev, threshold=thr, enabled=True))
    jobs = {j.category for j in db.execute(select(PollingJob)).scalars()}
    for cat, interval in POLLING:
        if cat not in jobs:
            db.add(PollingJob(category=cat, interval_seconds=interval))
    models = {m.product_number: m for m in db.execute(select(SwitchModel)).scalars()}
    for pn, spec in MODEL_CATALOG.items():
        row = models.get(pn)
        if row is None:
            row = SwitchModel(product_number=pn)
            db.add(row)
        row.name, row.access_ports, row.uplink_ports = spec.name, spec.access_ports, spec.uplink_ports
        row.poe_budget_w, row.port_layout = spec.poe_budget_w, spec.port_layout()
    db.flush()
