"""Change engine: validation, risk, approval, execution, verification, backups, bulk/canary, audit."""

from sqlalchemy import select

from app.drivers.simulator import state as st
from app.models import Alert, AuditLog, ChangeJob, ConfigBackup, Switch, SwitchPort
from app.services import polling
from tests.conftest import login, make_user


def _prep(sim_switches, n=1):
    ids = sim_switches(n)
    for c in ("inventory", "availability", "lldp"):
        polling.run_category(c, ids)
    return ids


def test_low_risk_job_executes_and_verifies(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "port_description", "switch_ids": ids,
                                          "params": {"items": [{"port": "7", "description": "Front desk"}]}})
    assert r.status_code == 201, r.text
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed" and job["risk"] == "low"
    res = job["results"][0]
    steps = [s["step"] for s in res["details"]["steps"]]
    assert steps[:6] == ["connect", "precheck", "pre_backup", "execute", "verify", "write_memory"]
    assert res["pre_backup_id"] and res["details"]["steps"][0]["simulated"] is True
    b = db.get(ConfigBackup, res["pre_backup_id"])
    assert b.trigger == "pre_change" and b.verify_status == "verified" and b.encrypted
    port = db.execute(select(SwitchPort).where(SwitchPort.switch_id == ids[0], SwitchPort.name == "7")).scalar_one()
    assert port.description == "Front desk"
    actions = {a.action for a in db.query(AuditLog).all()}
    assert {"job.create", "change.port_description", "job.finish", "backup.create"} <= actions


def test_invalid_params_rejected(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "admin", "ops")
    login(client, "ops")
    for op, params in [("port_admin", {"ports": ["1;reload"], "enabled": False}),
                       ("vlan_create", {"vlan_id": 5000, "name": "X"}),
                       ("vlan_create", {"vlan_id": 10, "name": "bad name"}),
                       ("port_vlan", {"ports": ["3"]}),
                       ("poe_config", {"ports": ["3"], "allocation_method": "value"}),
                       ("nonexistent", {})]:
        r = client.post("/api/v1/jobs", json={"operation": op, "switch_ids": ids, "params": params})
        assert r.status_code == 400, (op, r.text)


def test_uplink_shutdown_is_critical_and_needs_ack_and_approval(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "admin", "ops")
    make_user(db, "super_admin", "boss")
    login(client, "ops")
    body = {"operation": "port_admin", "switch_ids": ids, "params": {"ports": ["25"], "enabled": False}}
    pv = client.post("/api/v1/jobs/preview", json=body).json()
    assert pv["risk"] == "critical" and pv["requires_approval"] and any("uplink" in r for r in pv["reasons"])
    r = client.post("/api/v1/jobs", json=body)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "risk_acknowledgement_required"
    r = client.post("/api/v1/jobs", json={**body, "acknowledge_risk": True})
    assert r.status_code == 201 and r.json()["status"] == "pending_approval"
    jid = r.json()["id"]
    # admin cannot approve
    assert client.post(f"/api/v1/jobs/{jid}/approve", json={}).status_code == 403
    # port untouched until approval
    ip = db.get(Switch, ids[0]).mgmt_ip
    assert st.store.get(ip).ports["25"].enabled is True
    client.post("/api/v1/auth/logout")
    login(client, "boss")
    r = client.post(f"/api/v1/jobs/{jid}/reject", json={"comment": "not during business hours"})
    assert r.json()["status"] == "rejected"
    assert st.store.get(ip).ports["25"].enabled is True


def test_four_eyes_principle(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "super_admin", "boss")
    make_user(db, "super_admin", "boss2")
    login(client, "boss")
    r = client.post("/api/v1/jobs", json={"operation": "vlan_create", "switch_ids": ids,
                                          "params": {"vlan_id": 99, "name": "MGMT2"}})
    # renaming mgmt VLAN = medium -> not approval; use vlan delete (high)
    r = client.post("/api/v1/jobs", json={"operation": "vlan_delete", "switch_ids": ids, "params": {"vlan_id": 30}})
    jid = r.json()["id"]
    assert r.json()["status"] == "pending_approval"
    r = client.post(f"/api/v1/jobs/{jid}/approve", json={})
    assert r.status_code == 403 and "different user" in r.json()["detail"]["message"]
    client.post("/api/v1/auth/logout")
    login(client, "boss2")
    r = client.post(f"/api/v1/jobs/{jid}/approve", json={"comment": "ok"})
    assert r.status_code == 200
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "completed", job
    assert 30 not in st.store.get(db.get(Switch, ids[0]).mgmt_ip).vlans


def test_management_vlan_deletion_refused_by_precheck(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "super_admin", "boss")
    make_user(db, "super_admin", "boss2")
    login(client, "boss")
    r = client.post("/api/v1/jobs", json={"operation": "vlan_delete", "switch_ids": ids, "params": {"vlan_id": 99},
                                          "acknowledge_risk": True})
    assert r.json()["risk"] == "critical"
    jid = r.json()["id"]
    client.post("/api/v1/auth/logout")
    login(client, "boss2")
    client.post(f"/api/v1/jobs/{jid}/approve", json={})
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "failed" and "management VLAN" in job["results"][0]["message"]
    assert 99 in st.store.get(db.get(Switch, ids[0]).mgmt_ip).vlans
    assert db.execute(select(Alert).where(Alert.type == "config_operation_failed")).scalar_one()


def test_bulk_vlan_create_with_canary_and_batches(client, db, sim_switches):
    ids = _prep(sim_switches, 6)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "vlan_create", "switch_ids": ids, "batch_size": 2,
                                          "params": {"vlan_id": 150, "name": "IOT"}})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed" and job["progress"]["success"] == 6
    assert sorted({x["batch_index"] for x in job["results"]}) == list(range(6))
    for sid in ids:
        assert st.store.get(db.get(Switch, sid).mgmt_ip).vlans[150] == "IOT"


def test_canary_failure_stops_rollout(client, db, sim_switches):
    ids = _prep(sim_switches, 4)
    make_user(db, "admin", "ops")
    login(client, "ops")
    st.mutate(db.get(Switch, ids[0]).mgmt_ip, lambda s: setattr(s, "offline", True))
    r = client.post("/api/v1/jobs", json={"operation": "vlan_create", "switch_ids": ids, "max_retries": 0,
                                          "params": {"vlan_id": 151, "name": "CANARY"}})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed"
    statuses = [x["status"] for x in job["results"]]
    assert statuses[0] == "failed" and set(statuses[1:]) == {"skipped"}
    assert "canary" in job["summary"]["stopped_reason"]
    for sid in ids[1:]:
        assert 151 not in st.store.get(db.get(Switch, sid).mgmt_ip).vlans
    # retry only the failed/skipped ones after recovery
    st.mutate(db.get(Switch, ids[0]).mgmt_ip, lambda s: setattr(s, "offline", False))
    r = client.post(f"/api/v1/jobs/{job['id']}/retry")
    assert client.get(f"/api/v1/jobs/{r.json()['id']}").json()["status"] == "completed"


def test_bulk_requires_permission_and_supported_operation(client, db, sim_switches):
    ids = _prep(sim_switches, 2)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "port_speed", "switch_ids": ids,
                                          "params": {"port": "3", "mode": "auto"}})
    assert r.status_code == 400


def test_port_vlan_change_verification_and_precheck(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "port_vlan", "switch_ids": ids,
                                          "params": {"ports": ["3"], "untagged_vlan": 777}})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed" and "do not exist" in job["results"][0]["message"]
    r = client.post("/api/v1/jobs", json={"operation": "port_vlan", "switch_ids": ids,
                                          "params": {"ports": ["3"], "untagged_vlan": 30, "add_tagged": [20]}})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    p = db.execute(select(SwitchPort).where(SwitchPort.switch_id == ids[0], SwitchPort.name == "3")).scalar_one()
    db.refresh(p)
    assert p.untagged_vlan == 30 and 20 in p.tagged_vlans


def test_poe_and_security_operations(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "super_admin", "boss")
    make_user(db, "super_admin", "boss2")
    login(client, "boss")
    r = client.post("/api/v1/jobs", json={"operation": "poe_config", "switch_ids": ids,
                                          "params": {"ports": ["4"], "priority": "critical"}})
    assert client.get(f"/api/v1/jobs/{r.json()['id']}").json()["status"] == "completed"
    r = client.post("/api/v1/jobs", json={"operation": "poe_restart", "switch_ids": ids, "params": {"port": "4"}})
    assert r.json()["risk"] == "medium"
    assert client.get(f"/api/v1/jobs/{r.json()['id']}").json()["status"] == "completed"
    r = client.post("/api/v1/jobs", json={"operation": "snmpv3_user", "switch_ids": ids,
                                          "params": {"username": "nms", "auth_password": "AuthPass123",
                                                     "priv_password": "PrivPass123"}})
    jid = r.json()["id"]
    # secrets are never stored in clear in job params
    raw = db.get(ChangeJob, jid).params
    assert raw["auth_password"] == "********" and "AuthPass123" not in str(raw)
    client.post("/api/v1/auth/logout")
    login(client, "boss2")
    client.post(f"/api/v1/jobs/{jid}/approve", json={})
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "completed", job["results"][0]
    assert "AuthPass123" not in str(job)
    for a in db.query(AuditLog).all():
        assert "AuthPass123" not in str(a.details)
    cfg = st.store.get(db.get(Switch, ids[0]).mgmt_ip).running_config()
    assert "snmpv3 user nms" in cfg and "AuthPass123" not in cfg


def test_authorized_managers_precheck_blocks_lockout(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "super_admin", "boss")
    make_user(db, "super_admin", "boss2")
    login(client, "boss")
    r = client.post("/api/v1/jobs", json={"operation": "authorized_managers", "switch_ids": ids, "acknowledge_risk": True,
                                          "params": {"network": "203.0.113.0", "mask": "255.255.255.0"}})
    jid = r.json()["id"]
    client.post("/api/v1/auth/logout")
    login(client, "boss2")
    client.post(f"/api/v1/jobs/{jid}/approve", json={})
    job = client.get(f"/api/v1/jobs/{jid}").json()
    assert job["status"] == "failed" and "lock the application out" in job["results"][0]["message"]


def test_cancel_pending_job(client, db, sim_switches):
    ids = _prep(sim_switches)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "vlan_delete", "switch_ids": ids, "params": {"vlan_id": 30}})
    assert r.json()["status"] == "pending_approval"
    r = client.post(f"/api/v1/jobs/{r.json()['id']}/cancel")
    assert r.json()["status"] == "cancelled" and all(x["status"] == "cancelled" for x in r.json()["results"])


def test_templates(client, db, sim_switches):
    ids = _prep(sim_switches, 2)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/templates", json={"name": "Standard NTP", "operation": "sntp",
                                               "params": {"servers": ["10.0.0.10", "10.0.0.11"]}})
    assert r.status_code == 201
    r = client.post(f"/api/v1/templates/{r.json()['id']}/apply", json={"operation": "sntp", "switch_ids": ids})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    assert job["status"] == "completed", job
    assert client.post("/api/v1/templates", json={"name": "bad", "operation": "config_restore",
                                                  "params": {"backup_id": 1}}).status_code == 400


def test_change_waits_for_other_change_on_same_switch_and_fails_closed(client, db, sim_switches, monkeypatch):
    import redis

    from app.core.config import get_settings
    from app.services.jobs import engine

    ids = _prep(sim_switches)
    monkeypatch.setattr(engine, "CHANGE_LOCK_WAIT_SECONDS", 1)
    held = redis.Redis.from_url(get_settings().redis_url).lock(f"anm:change:{ids[0]}", timeout=30)
    assert held.acquire(blocking=False)
    try:
        make_user(db, "admin", "ops")
        login(client, "ops")
        r = client.post("/api/v1/jobs", json={"operation": "port_description", "switch_ids": ids,
                                              "params": {"items": [{"port": "7", "description": "Blocked"}]}})
        assert r.status_code == 201, r.text
        res = client.get(f"/api/v1/jobs/{r.json()['id']}").json()["results"][0]
        assert res["status"] == "failed" and "Another change" in res["message"]
    finally:
        held.release()
    port = db.execute(select(SwitchPort).where(SwitchPort.switch_id == ids[0], SwitchPort.name == "7")).scalar_one()
    db.refresh(port)
    assert port.description != "Blocked"


def test_speed_change_verified_from_running_config_without_rest(client, db, sim_switches):
    ids = _prep(sim_switches)
    ip = db.get(Switch, ids[0]).mgmt_ip
    st.mutate(ip, lambda s: setattr(s, "unsupported_rest", ["/ports", "/cli"]))  # no REST port data or CLI
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "port_speed", "switch_ids": ids,
                                          "params": {"port": "5", "mode": "100-full"}})
    job = client.get(f"/api/v1/jobs/{r.json()['id']}").json()
    res = job["results"][0]
    verify = next(s for s in res["details"]["steps"] if s["step"] == "verify")
    assert res["status"] == "success" and verify["actual"] == "100-full", res
    r = client.post("/api/v1/jobs", json={"operation": "port_speed", "switch_ids": ids,
                                          "params": {"port": "5", "mode": "auto"}})
    res = client.get(f"/api/v1/jobs/{r.json()['id']}").json()["results"][0]
    verify = next(s for s in res["details"]["steps"] if s["step"] == "verify")
    assert res["status"] == "success" and verify["actual"] == "auto", res
    st.mutate(ip, lambda s: setattr(s, "unsupported_rest", []))


def test_applied_change_is_not_rerun_when_readback_credential_fails(client, db, sim_switches, monkeypatch):
    from app.drivers.base import DriverError
    from app.services.jobs import operations

    ids = _prep(sim_switches)
    op = operations.REGISTRY["port_description"]
    calls = []
    real_execute = op.execute

    def counting_execute(*a, **kw):
        calls.append(1)
        return real_execute(*a, **kw)

    def failing_verify(*a, **kw):
        raise DriverError("auth_failed", "SNMP credential rejected: unknown SNMPv3 user name", protocol="snmp",
                          retriable=True)

    monkeypatch.setattr(op, "execute", counting_execute)
    monkeypatch.setattr(op, "verify", failing_verify)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/jobs", json={"operation": "port_description", "switch_ids": ids,
                                          "params": {"items": [{"port": "7", "description": "Once"}]}})
    res = client.get(f"/api/v1/jobs/{r.json()['id']}").json()["results"][0]
    assert res["status"] == "verify_failed" and res["attempts"] == 1 and len(calls) == 1
    assert "Change applied, verification failed (credential error)" in res["message"]
    assert res["details"]["applied"] is True
    backups = db.query(ConfigBackup).filter_by(switch_id=ids[0], trigger="pre_change").count()
    assert backups == 1
    assert st.store.get(db.get(Switch, ids[0]).mgmt_ip).ports["7"].description == "Once"
