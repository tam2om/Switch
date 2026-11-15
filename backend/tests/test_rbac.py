"""Backend authorization matrix: every role against representative protected endpoints."""

import pytest

from tests.conftest import login, make_user

ROLES = ["super_admin", "admin", "monitor", "viewer"]
ALL = set(ROLES)
ADMINS = {"super_admin", "admin"}
SUPER = {"super_admin"}
MON_UP = {"super_admin", "admin", "monitor"}

# (method, path, body, allowed roles)
MATRIX = [
    ("GET", "/api/v1/dashboard/overview", None, ALL),
    ("GET", "/api/v1/switches", None, ALL),
    ("GET", "/api/v1/vlans", None, ALL),
    ("GET", "/api/v1/poe/overview", None, ALL),
    ("GET", "/api/v1/topology", None, ALL),
    ("GET", "/api/v1/reports/availability", None, ALL),
    ("GET", "/api/v1/devices", None, MON_UP),
    ("GET", "/api/v1/alerts", None, MON_UP),
    ("GET", "/api/v1/events", None, MON_UP),
    ("GET", "/api/v1/reports/availability/export", None, MON_UP),
    ("GET", "/api/v1/jobs", None, ADMINS),
    ("GET", "/api/v1/backups", None, ADMINS),
    ("GET", "/api/v1/templates", None, ADMINS),
    ("GET", "/api/v1/users", None, ADMINS),
    ("GET", "/api/v1/settings", None, ADMINS),
    ("GET", "/api/v1/system/health", None, ADMINS),
    ("GET", "/api/v1/audit", None, ADMINS),
    ("GET", "/api/v1/audit/verify", None, SUPER),
    ("GET", "/api/v1/credentials", None, SUPER),
    ("GET", "/api/v1/integrations", None, SUPER),
    ("POST", "/api/v1/sites", {"name": "Site-X"}, ADMINS),
    ("POST", "/api/v1/switches", {"hostname": "sw-new", "mgmt_ip": "10.9.9.9"}, ADMINS),
    ("POST", "/api/v1/vlans", {"vlan_id": 300, "name": "TEST"}, ADMINS),
    ("PUT", "/api/v1/settings/polling.counters_seconds", {"value": 120}, ADMINS),
    ("PUT", "/api/v1/settings/auth.session_idle_minutes", {"value": 20}, SUPER),
    ("PUT", "/api/v1/credentials", {"kind": "rest", "purpose": "monitor", "username": "u", "password": "p"}, SUPER),
    ("POST", "/api/v1/simulator/seed", {"count": 1}, SUPER),
]


@pytest.mark.parametrize("role", ROLES)
def test_authorization_matrix(client, db, role):
    make_user(db, role, f"rbac-{role}")
    login(client, f"rbac-{role}")
    failures = []
    for i, (method, path, body, allowed) in enumerate(MATRIX):
        if body and "name" in body and path.endswith("/sites"):
            body = {"name": f"Site-{role}-{i}"}
        if path.endswith("/switches") and method == "POST":
            body = {"hostname": f"sw-{role}", "mgmt_ip": f"10.9.9.{ROLES.index(role) + 1}"}
        r = client.request(method, path, json=body)
        ok = r.status_code < 400
        if (role in allowed) != ok:
            failures.append(f"{method} {path}: role={role} status={r.status_code}")
        if role not in allowed:
            assert r.status_code == 403, f"{method} {path} should be 403 for {role}, got {r.status_code}"
    assert not failures, failures


def test_unauthenticated_is_rejected(client):
    for path in ("/api/v1/switches", "/api/v1/users", "/api/v1/dashboard/overview", "/api/v1/audit"):
        assert client.get(path).status_code == 401


def test_viewer_cannot_change_ports_or_ack(client, db, sim_switches):
    ids = sim_switches(1)
    make_user(db, "viewer", "viewer1")
    login(client, "viewer1")
    r = client.post("/api/v1/jobs", json={"operation": "port_admin", "switch_ids": ids,
                                          "params": {"ports": ["3"], "enabled": False}})
    assert r.status_code == 403
    assert client.post("/api/v1/alerts/1/ack").status_code == 403


def test_monitor_cannot_execute_jobs(client, db, sim_switches):
    ids = sim_switches(1)
    make_user(db, "monitor", "monitor1")
    login(client, "monitor1")
    for op, params in [("port_admin", {"ports": ["3"], "enabled": False}),
                       ("vlan_create", {"vlan_id": 77, "name": "X"}),
                       ("poe_config", {"ports": ["3"], "enabled": False}),
                       ("config_backup", {})]:
        r = client.post("/api/v1/jobs", json={"operation": op, "switch_ids": ids, "params": params})
        assert r.status_code == 403, op


def test_admin_cannot_approve_or_touch_security_settings(client, db):
    make_user(db, "admin", "admin1")
    login(client, "admin1")
    assert client.post("/api/v1/jobs/1/approve", json={}).status_code == 403
    assert client.put("/api/v1/settings/changes.allow_self_approval", json={"value": True}).status_code == 403
    assert client.get("/api/v1/credentials").status_code == 403
