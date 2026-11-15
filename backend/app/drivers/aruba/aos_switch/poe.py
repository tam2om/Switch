from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
from app.drivers.aruba.aos_switch.models import SLOT_IFINDEX_STRIDE
from app.drivers.base import PoePortInfo, PoeSummary

PRIORITY = {"PPP_LOW": "low", "PPP_HIGH": "high", "PPP_CRITICAL": "critical"}
PRIORITY_REV = {v: k for k, v in PRIORITY.items()}
ALLOC = {"PPAM_USAGE": "usage", "PPAM_CLASS": "class", "PPAM_VALUE": "value"}
ALLOC_REV = {v: k for k, v in ALLOC.items()}
DETECTION = {"PPDS_DELIVERING": "delivering", "PPDS_SEARCHING": "searching", "PPDS_DISABLED": "disabled",
             "PPDS_FAULT": "fault", "PPDS_TEST": "test", "PPDS_OTHER_FAULT": "fault", "PPDS_DENY": "denied"}


def parse_rest_poe(ports: dict, stats: dict | None) -> list[PoePortInfo]:
    st = {}
    for s in (stats or {}).get("port_poe_stats", []) or (stats or {}).get("port_poe_stats_element", []):
        st[str(s.get("port_id"))] = s
    out = []
    for p in ports.get("port_poe", []) or ports.get("port_poe_element", []):
        pid = str(p.get("port_id"))
        s = st.get(pid, {})
        det = DETECTION.get(s.get("poe_detection_status", ""), None) if s else None
        drawn = s.get("power_drawn_in_watts", s.get("actual_power_in_watts")) if s else None
        out.append(PoePortInfo(
            port=pid, enabled=p.get("is_poe_enabled"), priority=PRIORITY.get(p.get("poe_priority", "")),
            allocation_method=ALLOC.get(p.get("poe_allocation_method", "")),
            allocated_power_w=p.get("allocated_power_in_watts"),
            power_drawn_w=float(drawn) if drawn is not None else None,
            detection_status=det, power_class=str(s["power_class"]) if s.get("power_class") is not None else None,
            fault=s.get("over_current_count") and f"over-current x{s['over_current_count']}" or None,
        ))
    return out


def snmp_poe_summary(snmp: o.SnmpClient) -> PoeSummary:
    power = snmp.table(o.PETH_MAIN_POWER)
    cons = snmp.table(o.PETH_MAIN_CONSUMPTION)
    status = snmp.table(o.PETH_MAIN_STATUS)
    if not power:
        return PoeSummary()
    budget = sum(float(v) for v in power.values() if v is not None)
    consumed = sum(float(v) for v in cons.values() if v is not None) if cons else None
    st = next(iter(status.values()), None)
    return PoeSummary(budget_w=budget, consumed_w=consumed,
                      oper_status={1: "on", 2: "off", 3: "faulty"}.get(int(st)) if st is not None else None)


SNMP_DETECTION = {1: "disabled", 2: "searching", 3: "delivering", 4: "fault", 5: "test", 6: "fault"}
SNMP_PRIORITY = {1: "critical", 2: "high", 3: "low"}


def snmp_poe_ports(snmp: o.SnmpClient) -> list[PoePortInfo]:
    """Per-port PoE from POWER-ETHERNET-MIB (state, priority, class) and HP-ICF-POE-MIB (watts drawn).
    The allocated power value is only available over REST and stays unknown here."""
    cols = snmp.tables([o.PETH_PORT_ADMIN, o.PETH_PORT_DETECTION, o.PETH_PORT_PRIORITY, o.PETH_PORT_CLASS,
                        o.HP_POE_PORT_POWER_MW, o.HP_POE_PORT_ALLOCATE_BY])
    admin = cols[o.PETH_PORT_ADMIN]
    if not admin:
        return []
    names = snmp.table(o.IF_NAME)

    def i(col: str, idx: str) -> int | None:
        v = cols[col].get(idx)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    # The port index normally equals the ifIndex (group 1). If a chassis numbers ports per group instead
    # (the same port index appearing in several groups), map group g / port n to the slot ifIndex (g-1)*24+n.
    keys = sorted(admin, key=lambda k: [int(x) for x in k.split(".") if x.isdigit()])
    port_ids = [k.split(".")[-1] for k in keys]
    per_group = len(set(port_ids)) < len(port_ids)

    out = []
    for idx in keys:
        parts = idx.split(".")
        group, port_index = (parts[-2], parts[-1]) if len(parts) >= 2 else ("1", parts[0])
        if per_group and group.isdigit() and port_index.isdigit():
            port_index = str((int(group) - 1) * SLOT_IFINDEX_STRIDE + int(port_index))
        det = SNMP_DETECTION.get(i(o.PETH_PORT_DETECTION, idx) or 0)
        mw = i(o.HP_POE_PORT_POWER_MW, idx)
        cls = i(o.PETH_PORT_CLASS, idx)
        out.append(PoePortInfo(
            port=str(names.get(port_index, port_index)),
            enabled={1: True, 2: False}.get(i(o.PETH_PORT_ADMIN, idx) or 0),
            priority=SNMP_PRIORITY.get(i(o.PETH_PORT_PRIORITY, idx) or 0),
            allocation_method={1: "usage", 2: "class", 3: "value"}.get(i(o.HP_POE_PORT_ALLOCATE_BY, idx) or 0),
            power_drawn_w=round(mw / 1000, 1) if mw is not None else None,
            detection_status=det,
            power_class=str(cls - 1) if cls and det == "delivering" else None,
            fault="reported by device" if det == "fault" else None,
        ))
    return out
