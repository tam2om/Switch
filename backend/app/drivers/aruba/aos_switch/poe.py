from __future__ import annotations

from app.drivers.aruba.aos_switch import snmp_client as o
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
