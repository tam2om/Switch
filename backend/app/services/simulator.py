"""Create/remove simulated switches. Simulated switches use addresses from 198.18.0.0/15 (RFC 2544 benchmarking
range, never routed in production), the 'simulator' driver and switch-specific simulator credentials, and are
labelled SIMULATED everywhere."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.drivers.simulator import state as st
from app.drivers.simulator.driver import SIM_CREDENTIALS, SIM_HOST_KEY
from app.models import Site, Switch, SwitchGroup, SwitchGroupMember
from app.services import credentials


def sim_ip(index: int) -> str:
    return f"198.18.{index // 250}.{index % 250 + 1}"


def seed(db: Session, count: int) -> dict:
    from app.drivers.aruba.aos_switch.ssh_client import fingerprint

    site = db.execute(select(Site).where(Site.name == "Simulated Lab")).scalar_one_or_none()
    if site is None:
        site = Site(name="Simulated Lab", description="Simulator only - not real hardware")
        db.add(site)
        db.flush()
    group = db.execute(select(SwitchGroup).where(SwitchGroup.name == "Simulated switches")).scalar_one_or_none()
    if group is None:
        group = SwitchGroup(name="Simulated switches", description="All simulator switches")
        db.add(group)
        db.flush()
    existing = {s.mgmt_ip for s in db.execute(select(Switch).where(Switch.is_simulated.is_(True))).scalars()}
    created = []
    for i in range(1, count + 1):
        ip = sim_ip(i)
        if ip in existing:
            continue
        building = f"B{1 + (i - 1) // 10}"
        state = st.get_or_create(ip, i, count, location=f"Sim {building} Floor {1 + (i % 4)}")
        sw = Switch(hostname=state.hostname, mgmt_ip=ip, driver="simulator", is_simulated=True, site_id=site.id,
                    building=building, floor=str(1 + (i % 4)), location=state.location,
                    department=["IT", "Finance", "Operations", "HR", "Security"][i % 5], uplink_ports=state.profile.uplinks[:2],
                    status="unknown", ssh_host_key=SIM_HOST_KEY,
                    ssh_host_key_fingerprint=fingerprint(SIM_HOST_KEY.split()[1]), ssh_host_key_trusted=True,
                    notes="SIMULATED SWITCH - not real hardware")
        db.add(sw)
        db.flush()
        db.add(SwitchGroupMember(group_id=group.id, switch_id=sw.id))
        c = SIM_CREDENTIALS
        for purpose in ("monitor", "config"):
            credentials.upsert(db, switch_id=sw.id, kind="rest", purpose=purpose, username=c["rest"]["username"],
                               secrets={"password": c["rest"]["password"]}, name="simulator")
            credentials.upsert(db, switch_id=sw.id, kind="ssh", purpose=purpose, username=c["ssh"]["username"],
                               secrets={"password": c["ssh"]["password"]}, params={"port": 22}, name="simulator")
        credentials.upsert(db, switch_id=sw.id, kind="snmpv3", purpose="monitor", username=c["snmpv3"]["username"],
                           secrets={"auth_password": c["snmpv3"]["auth_password"],
                                    "priv_password": c["snmpv3"]["priv_password"]},
                           params={"auth_protocol": "sha", "priv_protocol": "aes"}, name="simulator")
        created.append(sw.id)
    db.flush()
    return {"created": len(created), "switch_ids": created, "total_simulated": len(existing) + len(created)}


def remove_all(db: Session) -> int:
    rows = db.execute(select(Switch).where(Switch.is_simulated.is_(True))).scalars().all()
    for sw in rows:
        st.store.delete(sw.mgmt_ip)
        db.delete(sw)
    return len(rows)


def inject(ip: str, *, offline: bool | None = None, poe_fault_port: str | None = None,
           flapping_port: str | None = None, clear: bool = False) -> dict:
    def fn(sw: st.SimSwitch) -> dict:
        if clear:
            sw.offline = False
            for p in sw.ports.values():
                p.poe_fault = False
                p.flapping = False
        if offline is not None:
            sw.offline = offline
        if poe_fault_port:
            sw.ports[poe_fault_port].poe_fault = True
        if flapping_port:
            sw.ports[flapping_port].flapping = True
            sw.ports[flapping_port].link = True
        return {"offline": sw.offline, "poe_faults": [n for n, p in sw.ports.items() if p.poe_fault],
                "flapping": [n for n, p in sw.ports.items() if p.flapping]}

    return st.mutate(ip, fn)
