import time

from sqlalchemy import func, select

from app.drivers.simulator import state as st
from app.models import (
    Alert,
    MacLearnedEntry,
    PoeConfiguration,
    PortMetric,
    Switch,
    SwitchEvent,
    SwitchMetric,
    SwitchNeighbor,
    SwitchPort,
    SwitchVlan,
)
from app.services import polling
from tests.conftest import login, make_user


def _all(ids, cats=("inventory", "availability", "health", "temperature", "poe", "mac", "lldp", "counters")):
    for c in cats:
        res = polling.run_category(c, ids)
        assert res["failed"] == 0, (c, res)


def test_full_poll_cycle_populates_database(db, sim_switches):
    ids = sim_switches(3)
    _all(ids)
    sw = db.get(Switch, ids[0])
    assert sw.status == "online" and sw.product_number == "JL356A" and sw.firmware == "YC.16.11.0018"
    assert sw.capabilities["resources"]["ports.read"] is True and sw.rest_api_version == "v7"
    assert sw.cpu_pct is not None and sw.mem_pct is not None and sw.temperature_c is not None
    assert sw.poe_budget_w == 370.0 and sw.mgmt_vlan == 99
    assert db.execute(select(func.count()).where(SwitchPort.switch_id == sw.id)).scalar_one() == 28
    p25 = db.execute(select(SwitchPort).where(SwitchPort.switch_id == sw.id, SwitchPort.name == "25")).scalar_one()
    assert p25.is_uplink and p25.port_type == "SFP+" and 99 in p25.tagged_vlans
    assert db.execute(select(func.count()).where(SwitchVlan.switch_id == sw.id)).scalar_one() == 5
    assert db.execute(select(func.count()).where(PoeConfiguration.switch_id == sw.id)).scalar_one() == 24
    assert db.execute(select(func.count()).where(MacLearnedEntry.switch_id == sw.id)).scalar_one() > 0
    # LLDP links resolve to inventory switches
    n = db.execute(select(SwitchNeighbor).where(SwitchNeighbor.switch_id == ids[0], SwitchNeighbor.local_port == "26")).scalar_one()
    assert n.remote_switch_id == ids[1]
    assert db.execute(select(func.count()).select_from(SwitchMetric)).scalar_one() > 0


def test_counter_rates_computed_on_second_poll(db, sim_switches):
    ids = sim_switches(1)
    _all(ids, ("inventory", "counters"))
    time.sleep(1.1)
    polling.run_category("counters", ids)
    rates = db.execute(select(SwitchPort.in_bps).where(SwitchPort.switch_id == ids[0], SwitchPort.oper_up.is_(True),
                                                       SwitchPort.in_bps.is_not(None))).scalars().all()
    assert rates and all(r >= 0 for r in rates)
    assert db.execute(select(func.count()).select_from(PortMetric)).scalar_one() >= 56


def test_counter_wrap_handled():
    from datetime import UTC, datetime

    from app.drivers.base import PortCounters

    class D:
        def get_port_counters(self):
            return [PortCounters(if_index=1, name="1", in_octets=100, out_octets=100, in_errors=0, out_errors=0)]

    # simulate previous counter near 2**64
    from app.db.session import session_factory

    with session_factory()() as db:
        from app.services.simulator import seed

        sid = seed(db, 1)["switch_ids"][0]
        db.add(SwitchPort(switch_id=sid, if_index=1, name="1", tagged_vlans=[],
                          last_counters={"ts": datetime.now(UTC).timestamp() - 10, "in": 2**64 - 900, "out": 0,
                                         "in_err": 0, "out_err": 0}))
        db.commit()
        sw = db.get(Switch, sid)
        polling.poll_counters(db, sw, D())
        p = db.execute(select(SwitchPort).where(SwitchPort.switch_id == sid)).scalar_one()
        assert 0 < p.in_bps < 2000  # (900+100) bytes * 8 / ~10s


def test_offline_detection_and_recovery_alerts(db, sim_switches):
    ids = sim_switches(1)
    _all(ids, ("inventory", "availability"))
    ip = db.get(Switch, ids[0]).mgmt_ip
    st.mutate(ip, lambda s: setattr(s, "offline", True))
    polling.run_category("availability", ids)
    db.expire_all()
    assert db.get(Switch, ids[0]).status == "online"  # one failure is tolerated
    polling.run_category("availability", ids)
    db.expire_all()
    assert db.get(Switch, ids[0]).status == "offline"
    assert db.execute(select(Alert).where(Alert.type == "switch_offline", Alert.status == "active")).scalar_one()
    st.mutate(ip, lambda s: setattr(s, "offline", False))
    polling.run_category("availability", ids)
    db.expire_all()
    assert db.get(Switch, ids[0]).status == "online"
    assert db.execute(select(Alert).where(Alert.type == "switch_offline")).scalar_one().status == "resolved"
    assert db.execute(select(SwitchEvent).where(SwitchEvent.type == "switch.recovered")).first()


def test_poe_fault_and_threshold_alerts(db, sim_switches):
    ids = sim_switches(1)
    _all(ids, ("inventory",))
    ip = db.get(Switch, ids[0]).mgmt_ip
    st.mutate(ip, lambda s: setattr(s.ports["2"], "poe_fault", True))
    polling.run_category("poe", ids)
    a = db.execute(select(Alert).where(Alert.type == "poe_fault")).scalar_one()
    assert a.port_name == "2" and a.status == "active"
    from app.services import settings as sysset

    sysset.set_value(db, "alerts.poe_threshold", 1, None)
    db.commit()
    polling.run_category("poe", ids)
    assert db.execute(select(Alert).where(Alert.type == "high_poe")).scalar_one()


def test_new_device_detection(db, sim_switches):
    ids = sim_switches(1)
    _all(ids, ("inventory", "mac"))
    ip = db.get(Switch, ids[0]).mgmt_ip

    def add(s):
        s.ports["1"].link = True
        s.macs.append({"mac": "aa:bb:cc:00:11:22", "vlan": 10, "port": "1"})

    st.mutate(ip, add)
    polling.run_category("mac", ids)
    a = db.execute(select(Alert).where(Alert.type == "new_device")).scalar_one()
    assert "aa:bb:cc:00:11:22" in a.message


def test_auth_failure_marks_warning_not_offline(db, sim_switches):
    from app.services import credentials

    ids = sim_switches(1)
    credentials.upsert(db, switch_id=ids[0], kind="snmpv3", purpose="monitor", username="sim-snmp",
                       secrets={"auth_password": "wrongwrong", "priv_password": "wrongwrong"})
    db.commit()
    for _ in range(3):
        polling.run_category("availability", ids)
    db.expire_all()
    sw = db.get(Switch, ids[0])
    assert sw.status == "warning" and "authentication" in sw.status_reason.lower()


def test_dashboard_and_metrics_api(client, db, sim_switches):
    ids = sim_switches(3)
    _all(ids)
    time.sleep(1.1)
    polling.run_category("counters", ids)
    make_user(db, "viewer", "dash")
    login(client, "dash")
    o = client.get("/api/v1/dashboard/overview").json()
    assert o["switches"]["total"] == 3 and o["switches"]["online"] == 3 and o["switches"]["simulated"] == 3
    assert o["ports"]["total"] == 84 and o["poe"]["budget_w"] == 1110.0
    assert o["traffic"]["available"] is True and o["top_ports"]
    m = client.get(f"/api/v1/metrics/switches/{ids[0]}", params={"range": "1h"}).json()
    assert m["points"] and m["points"][-1]["cpu_pct"] is not None
    assert client.get(f"/api/v1/metrics/switches/{ids[0]}/ports/5", params={"range": "1h"}).status_code == 200
    assert client.get("/api/v1/metrics/traffic", params={"range": "1h"}).json()["points"]
    for kind in ("availability", "bandwidth", "ports"):
        r = client.get(f"/api/v1/reports/{kind}", params={"period": "daily"})
        assert r.status_code == 200 and r.json()["rows"], kind
    assert client.get(f"/api/v1/switches/{ids[0]}/ports").json()[0]["macs"] == []  # viewer: no MAC data
    assert client.get("/api/v1/topology").json()["edges"]


def test_stale_flag(client, db, sim_switches):
    ids = sim_switches(1)
    make_user(db, "viewer", "stale-viewer")
    login(client, "stale-viewer")
    d = client.get(f"/api/v1/switches/{ids[0]}").json()
    assert d["metrics"]["stale"] is True and d["metrics"]["cpu_pct"] is None  # never measured -> no values
