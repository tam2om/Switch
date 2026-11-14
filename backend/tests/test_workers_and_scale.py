"""Background tasks, worker recovery and simulated fleet scale (100 switches / 2,800 ports)."""

import time
from datetime import timedelta

from sqlalchemy import func, select

from app.db.base import utcnow
from app.models import ChangeJob, ChangeJobResult, PollingJob, PortMetric, Switch, SwitchPort
from app.services import polling
from app.workers import tasks


def test_scheduler_tick_dispatches_due_categories(db, sim_switches, monkeypatch):
    sim_switches(2)
    calls = []
    monkeypatch.setattr(tasks.poll_category, "delay", lambda c: calls.append(c))
    monkeypatch.setattr(tasks.scheduled_backups, "delay", lambda: None)
    res = tasks.scheduler_tick()
    assert set(res["dispatched"]) == {"availability", "counters", "health", "poe", "temperature", "mac", "lldp", "inventory"}
    calls.clear()
    res = tasks.scheduler_tick()
    assert res["dispatched"] == []  # nothing due again immediately
    db.query(PollingJob).filter_by(category="availability").update({"last_run_at": utcnow() - timedelta(seconds=31)})
    db.commit()
    assert tasks.scheduler_tick()["dispatched"] == ["availability"]


def test_worker_crash_recovery_marks_job_failed(db, sim_switches):
    ids = sim_switches(1)
    j = ChangeJob(operation="vlan_create", title="x", params={"vlan_id": 5, "name": "X"}, risk="low", status="running",
                  started_at=utcnow() - timedelta(hours=2), requested_by_name="ops")
    db.add(j)
    db.flush()
    db.add(ChangeJobResult(job_id=j.id, switch_id=ids[0], status="running"))
    db.commit()
    import app.workers.tasks as t

    orig = t.poll_category.delay
    t.poll_category.delay = lambda *a, **k: None
    try:
        t.scheduler_tick()
    finally:
        t.poll_category.delay = orig
    db.expire_all()
    j = db.get(ChangeJob, j.id)
    assert j.status == "failed" and "verify the switch state" in j.error
    assert j.results[0].status == "failed"


def test_maintenance_task(db):
    out = tasks.maintenance()
    assert "audit" in out and "sessions" in out


def test_scheduled_backups_task(db, sim_switches):
    sim_switches(2)
    assert tasks.scheduled_backups() == {"ok": 2, "failed": 0}
    assert tasks.scheduled_backups() == {"ok": 2, "failed": 0}  # deduplicated (no new rows)
    from app.models import ConfigBackup

    assert db.query(ConfigBackup).count() == 2


def test_hundred_switch_fleet_polling(db, sim_switches, client):
    ids = sim_switches(100)
    t0 = time.monotonic()
    inv = polling.run_category("inventory", ids)
    t_inv = time.monotonic() - t0
    assert inv["failed"] == 0 and inv["switches"] == 100
    for cat in ("availability", "health", "poe", "counters"):
        t1 = time.monotonic()
        res = polling.run_category(cat, ids)
        assert res["failed"] == 0, (cat, res)
        assert time.monotonic() - t1 < 60, f"{cat} too slow"
    assert db.execute(select(func.count()).select_from(SwitchPort)).scalar_one() == 2800
    time.sleep(1.0)
    polling.run_category("counters", ids)
    assert db.execute(select(func.count()).select_from(PortMetric)).scalar_one() == 5600
    # Dashboard must stay responsive at fleet scale.
    from tests.conftest import login, make_user

    make_user(db, "viewer", "dash")
    login(client, "dash")
    t2 = time.monotonic()
    o = client.get("/api/v1/dashboard/overview")
    elapsed = time.monotonic() - t2
    assert o.status_code == 200 and o.json()["switches"]["total"] == 100 and o.json()["ports"]["total"] == 2800
    assert elapsed < 3.0, f"dashboard took {elapsed:.2f}s"
    assert client.get("/api/v1/switches", params={"page_size": 500}).json()["total"] == 100
    assert client.get("/api/v1/vlans/matrix").status_code == 200
    print(f"inventory 100 switches: {t_inv:.1f}s, dashboard: {elapsed * 1000:.0f} ms")


def test_slow_switch_does_not_block_fleet(db, sim_switches, monkeypatch):
    ids = sim_switches(5)
    from app.drivers.simulator import snmp as simsnmp

    orig = simsnmp.SimSnmpTransport.get
    slow_ip = db.get(Switch, ids[0]).mgmt_ip

    def slow_get(self, oids):
        if self.ip == slow_ip:
            time.sleep(1.5)
        return orig(self, oids)

    monkeypatch.setattr(simsnmp.SimSnmpTransport, "get", slow_get)
    t0 = time.monotonic()
    res = polling.run_category("health", ids)
    assert res["failed"] == 0 and time.monotonic() - t0 < 3.0  # concurrent, bounded by the slowest switch
