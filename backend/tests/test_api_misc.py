from app.models import SwitchCredential
from tests.conftest import login, make_user


def test_switch_inventory_crud(client, db):
    make_user(db, "admin", "ops")
    login(client, "ops")
    site = client.post("/api/v1/sites", json={"name": "HQ", "address": "Main St"}).json()
    grp = client.post("/api/v1/groups", json={"name": "Floor 1"}).json()
    r = client.post("/api/v1/switches", json={"hostname": "core-sw-01", "mgmt_ip": "10.10.0.11", "site_id": site["id"],
                                              "building": "A", "floor": "1", "department": "IT", "mgmt_vlan": 99,
                                              "uplink_ports": ["25", "26"], "group_ids": [grp["id"]]})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["is_simulated"] is False and r.json()["status"] == "unknown"
    assert client.post("/api/v1/switches", json={"hostname": "dup", "mgmt_ip": "10.10.0.11"}).status_code == 409
    assert client.post("/api/v1/switches", json={"hostname": "bad", "mgmt_ip": "not-an-ip"}).status_code == 422
    assert client.post("/api/v1/switches", json={"hostname": "bad;rm", "mgmt_ip": "10.1.1.1"}).status_code == 422
    assert client.post("/api/v1/switches", json={"hostname": "t", "mgmt_ip": "10.1.1.2",
                                                 "protocols": {"telnet": True}}).status_code == 422
    lst = client.get("/api/v1/switches", params={"q": "core"}).json()
    assert lst["total"] == 1 and lst["items"][0]["groups"][0]["name"] == "Floor 1"
    assert client.get("/api/v1/switches", params={"group_id": grp["id"]}).json()["total"] == 1
    r = client.patch(f"/api/v1/switches/{sid}", json={"location": "Rack 3", "monitoring_enabled": False})
    assert r.json()["location"] == "Rack 3" and r.json()["monitoring_enabled"] is False
    assert client.post(f"/api/v1/switches/{sid}/poll").status_code == 409  # monitoring disabled
    assert client.request("DELETE", f"/api/v1/switches/{sid}", json={"confirm_hostname": "wrong"}).status_code == 400
    assert client.request("DELETE", f"/api/v1/switches/{sid}", json={"confirm_hostname": "core-sw-01"}).status_code == 200


def test_real_switch_without_credentials_reports_clearly(client, db):
    make_user(db, "admin", "ops")
    login(client, "ops")
    sid = client.post("/api/v1/switches", json={"hostname": "sw-x", "mgmt_ip": "10.200.0.1",
                                                "protocols": {"rest": True, "snmp": False, "ssh": False}}).json()["id"]
    r = client.post(f"/api/v1/switches/{sid}/poll", params={"category": "health"}).json()
    assert r["ok"] is False and r["error"]["code"] == "no_credentials"
    sw = client.get(f"/api/v1/switches/{sid}").json()
    assert sw["status"] == "warning" and "credentials" in sw["status_reason"]


def test_credentials_encrypted_and_masked(client, db):
    make_user(db, "super_admin", "boss")
    login(client, "boss")
    r = client.put("/api/v1/credentials", json={"kind": "snmpv3", "purpose": "monitor", "username": "nms",
                                                 "auth_password": "AuthSecret-1", "priv_password": "PrivSecret-1"})
    assert r.status_code == 200 and r.json()["secret"] == "********"
    assert client.put("/api/v1/credentials", json={"kind": "snmpv3", "purpose": "config", "username": "x",
                                                   "auth_password": "AuthSecret-1",
                                                   "priv_password": "PrivSecret-1"}).status_code == 400
    assert client.put("/api/v1/credentials", json={"kind": "snmpv3", "purpose": "monitor", "username": "x",
                                                   "auth_password": "short", "priv_password": "short"}).status_code == 400
    c = db.query(SwitchCredential).one()
    assert "AuthSecret-1" not in c.secret_enc and c.secret_enc.startswith("v1:")
    listing = client.get("/api/v1/credentials").text
    assert "AuthSecret-1" not in listing and "PrivSecret-1" not in listing


def test_settings_validation_and_audit(client, db):
    make_user(db, "super_admin", "boss")
    login(client, "boss")
    assert client.put("/api/v1/settings/polling.counters_seconds", json={"value": 5}).status_code == 400
    assert client.put("/api/v1/settings/audit.retention_days", json={"value": 30}).status_code == 400
    assert client.put("/api/v1/settings/nonexistent", json={"value": 1}).status_code == 404
    assert client.put("/api/v1/settings/polling.counters_seconds", json={"value": 120}).json()["value"] == 120
    s = {x["key"]: x for x in client.get("/api/v1/settings").json()}
    assert s["polling.counters_seconds"]["value"] == 120


def test_vlan_catalogue_matrix_consistency_compare(client, db, sim_switches):
    from app.services import polling

    ids = sim_switches(2)
    polling.run_category("inventory", ids)
    make_user(db, "admin", "ops")
    login(client, "ops")
    for vid, name in [(10, "DATA"), (20, "VOICE"), (99, "MGMT"), (40, "PRINTERS")]:
        assert client.post("/api/v1/vlans", json={"vlan_id": vid, "name": name, "is_management": vid == 99}).status_code == 201
    cat = {v["vlan_id"]: v for v in client.get("/api/v1/vlans").json()}
    assert cat[10]["switch_count"] == 2 and cat[40]["switch_count"] == 0 and cat[30]["in_catalogue"] is False
    m = client.get("/api/v1/vlans/matrix").json()
    assert 40 in m["vlans"] and m["rows"][0]["cells"]["10"]["untagged"] >= 0
    c = client.get("/api/v1/vlans/consistency").json()
    types = {i["type"] for i in c["issues"]}
    assert "missing" in types and "unplanned" in types and c["consistent"] is False
    cmp = client.get("/api/v1/vlans/compare", params={"a": ids[0], "b": ids[1]}).json()
    assert all(r["status"] == "both" for r in cmp["rows"])
    sv = client.get(f"/api/v1/switches/{ids[0]}/vlans").json()
    assert any(v["vlan_id"] == 99 and v["is_management"] for v in sv)


def test_alerts_ack_and_rules(client, db, sim_switches):
    from app.services import alerts as asvc

    ids = sim_switches(1)
    from app.models import Switch

    asvc.raise_alert(db, type="high_cpu", switch=db.get(Switch, ids[0]), message="CPU high")
    db.commit()
    make_user(db, "monitor", "mon")
    login(client, "mon")
    lst = client.get("/api/v1/alerts").json()
    assert lst["total"] == 1
    aid = lst["items"][0]["id"]
    assert client.post(f"/api/v1/alerts/{aid}/ack").json()["status"] == "acknowledged"
    assert client.patch("/api/v1/alert-rules/1", json={"enabled": False}).status_code == 403
    client.post("/api/v1/auth/logout")
    make_user(db, "admin", "ops")
    login(client, "ops")
    rules = client.get("/api/v1/alert-rules").json()
    rid = next(r["id"] for r in rules if r["type"] == "high_cpu")
    assert client.patch(f"/api/v1/alert-rules/{rid}", json={"threshold": 95, "notify_email": True,
                                                            "recipients": ["noc@example.com"]}).status_code == 200


def test_alert_dedup_and_disabled_rule(db, sim_switches):
    from app.models import Alert, AlertRule, Switch
    from app.services import alerts as asvc

    sw = db.get(Switch, sim_switches(1)[0])
    a1 = asvc.raise_alert(db, type="high_memory", switch=sw, message="m1")
    a2 = asvc.raise_alert(db, type="high_memory", switch=sw, message="m2")
    db.commit()
    assert a1.id == a2.id and a2.occurrences == 2
    db.query(AlertRule).filter_by(type="high_cpu").update({"enabled": False})
    assert asvc.raise_alert(db, type="high_cpu", switch=sw, message="x") is None
    assert db.query(Alert).count() == 1


def test_notification_without_smtp_marks_failed(db, sim_switches):
    from app.models import AlertRule, Notification, Switch
    from app.services import alerts as asvc

    sw = db.get(Switch, sim_switches(1)[0])
    db.query(AlertRule).filter_by(type="switch_offline").update({"notify_email": True, "recipients": ["a@example.com"]})
    asvc.raise_alert(db, type="switch_offline", switch=sw, message="down")
    db.commit()
    res = asvc.send_pending_notifications(db)
    db.commit()
    assert res == {"sent": 0, "failed": 1}
    assert db.query(Notification).one().error == "SMTP is not configured"


def test_topology_manual_links(client, db, sim_switches):
    ids = sim_switches(2)
    make_user(db, "admin", "ops")
    login(client, "ops")
    r = client.post("/api/v1/topology/links", json={"switch_id": ids[0], "local_port": "27",
                                                    "remote_switch_id": ids[1], "remote_port": "27"})
    assert r.status_code == 201
    topo = client.get("/api/v1/topology").json()
    assert any(e["source_type"] == "manual" for e in topo["edges"])
    assert client.delete(f"/api/v1/topology/links/{r.json()['id']}").status_code == 200


def test_devices_search(client, db, sim_switches):
    from app.services import polling

    ids = sim_switches(1)
    polling.run_category("mac", ids)
    make_user(db, "monitor", "mon")
    login(client, "mon")
    d = client.get("/api/v1/devices").json()
    assert d["total"] > 0
    mac = d["items"][0]["mac"]
    assert client.get("/api/v1/devices", params={"q": mac[:8]}).json()["total"] >= 1
    assert client.get("/api/v1/search", params={"q": "SIM-SW"}).json()["switches"]


def test_system_health_and_capabilities(client, db):
    make_user(db, "admin", "ops")
    login(client, "ops")
    h = client.get("/api/v1/system/health").json()
    assert h["database"]["ok"] and h["database"]["timescaledb"] and h["storage"]["ok"]
    m = client.get("/api/v1/capabilities/matrix").json()
    assert any(r["key"] == "ports.read" for r in m["registry"])


def test_simulator_fault_injection_only_for_simulated(client, db, sim_switches):
    ids = sim_switches(1)
    make_user(db, "super_admin", "boss")
    login(client, "boss")
    assert client.post(f"/api/v1/simulator/switches/{ids[0]}/fault", json={"offline": True}).json()["offline"] is True
    real = client.post("/api/v1/switches", json={"hostname": "real-1", "mgmt_ip": "10.50.0.1"}).json()
    assert client.post(f"/api/v1/simulator/switches/{real['id']}/fault", json={"offline": True}).status_code == 400


def test_ssh_host_key_trust_flow(client, db, sim_switches):
    ids = sim_switches(1)
    make_user(db, "super_admin", "boss")
    login(client, "boss")
    fp = client.post(f"/api/v1/switches/{ids[0]}/ssh-host-key/fetch").json()["fingerprint"]
    assert fp.startswith("SHA256:")
    assert client.get(f"/api/v1/switches/{ids[0]}").json()["ssh_host_key_trusted"] is False
    assert client.post(f"/api/v1/switches/{ids[0]}/ssh-host-key/trust", json={"fingerprint": "SHA256:x"}).status_code == 400
    assert client.post(f"/api/v1/switches/{ids[0]}/ssh-host-key/trust", json={"fingerprint": fp}).json()["trusted"]


def test_sql_injection_attempts_are_inert(client, db, sim_switches):
    sim_switches(1)
    make_user(db, "admin", "ops")
    login(client, "ops")
    for q in ["' OR 1=1 --", "'; DROP TABLE switches; --", "%' UNION SELECT password_hash FROM users --"]:
        r = client.get("/api/v1/switches", params={"q": q})
        assert r.status_code == 200 and r.json()["total"] == 0
        assert client.get("/api/v1/users", params={"q": q}).json()["total"] == 0
    assert client.get("/api/v1/switches").json()["total"] == 1


def test_openapi_available(client):
    spec = client.get("/api/openapi.json").json()
    assert len(spec["paths"]) > 80


def test_api_docs_disabled_by_default(monkeypatch):
    from app.core.config import Settings

    monkeypatch.delenv("ANM_API_DOCS_ENABLED", raising=False)
    assert Settings().api_docs_enabled is False
