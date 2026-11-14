from app.models import AuditLog
from tests.conftest import PASSWORD, login, make_user

NEW_PW = "Another-Strong-Pass-55"


def test_superadmin_full_user_lifecycle(client, db):
    make_user(db, "super_admin", "root")
    login(client, "root")
    r = client.post("/api/v1/users", json={"username": "alice", "full_name": "Alice", "email": "alice@corp.example.com",
                                           "role": "admin", "password": NEW_PW})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert r.json()["must_change_password"] is True
    assert client.get("/api/v1/users", params={"q": "ali"}).json()["total"] == 1
    assert client.get("/api/v1/users", params={"role": "admin"}).json()["total"] == 1
    r = client.patch(f"/api/v1/users/{uid}", json={"role": "monitor", "is_active": False})
    assert r.status_code == 200 and r.json()["role"] == "monitor" and r.json()["is_active"] is False
    assert client.get("/api/v1/users", params={"active": False}).json()["total"] == 1
    assert client.post(f"/api/v1/users/{uid}/password", json={"password": "Reset-By-Admin-88"}).status_code == 200
    assert client.post(f"/api/v1/users/{uid}/unlock").status_code == 200
    acts = {a.action for a in db.query(AuditLog).all()}
    assert {"user.create", "user.update", "user.password_set_by_admin", "user.unlock"} <= acts
    assert client.delete(f"/api/v1/users/{uid}").status_code == 200


def test_duplicate_and_weak_password(client, db):
    make_user(db, "super_admin", "root")
    login(client, "root")
    assert client.post("/api/v1/users", json={"username": "bob", "role": "viewer", "password": "weak"}).status_code == 400
    assert client.post("/api/v1/users", json={"username": "bob", "role": "viewer", "password": NEW_PW}).status_code == 201
    assert client.post("/api/v1/users", json={"username": "BOB", "role": "viewer", "password": NEW_PW}).status_code == 409


def test_admin_restrictions(client, db):
    sa = make_user(db, "super_admin", "root")
    other_admin = make_user(db, "admin", "admin2")
    make_user(db, "admin", "admin1")
    login(client, "admin1")
    # cannot create super admin or admin
    assert client.post("/api/v1/users", json={"username": "xx1", "role": "super_admin", "password": NEW_PW}).status_code == 403
    assert client.post("/api/v1/users", json={"username": "xx2", "role": "admin", "password": NEW_PW}).status_code == 403
    # can create monitor/viewer
    r = client.post("/api/v1/users", json={"username": "mon1", "role": "monitor", "password": NEW_PW})
    assert r.status_code == 201
    # cannot promote monitor to admin/super admin
    assert client.patch(f"/api/v1/users/{r.json()['id']}", json={"role": "super_admin"}).status_code == 403
    assert client.patch(f"/api/v1/users/{r.json()['id']}", json={"role": "admin"}).status_code == 403
    # cannot modify super admin or other admins
    assert client.patch(f"/api/v1/users/{sa.id}", json={"full_name": "x"}).status_code == 403
    assert client.patch(f"/api/v1/users/{sa.id}", json={"is_active": False}).status_code == 403
    assert client.post(f"/api/v1/users/{sa.id}/password", json={"password": NEW_PW}).status_code == 403
    assert client.post(f"/api/v1/users/{sa.id}/reset-token").status_code == 403
    assert client.delete(f"/api/v1/users/{other_admin.id}").status_code == 403


def test_no_self_escalation_or_self_disable(client, db):
    me = make_user(db, "super_admin", "root")
    make_user(db, "super_admin", "root2")
    login(client, "root")
    assert client.patch(f"/api/v1/users/{me.id}", json={"role": "viewer"}).status_code == 403
    assert client.patch(f"/api/v1/users/{me.id}", json={"is_active": False}).status_code == 403
    assert client.delete(f"/api/v1/users/{me.id}").status_code == 403
    client.post("/api/v1/auth/logout")
    viewer = make_user(db, "viewer", "vv")
    login(client, "vv")
    assert client.patch(f"/api/v1/users/{viewer.id}", json={"role": "super_admin"}).status_code == 403


def test_last_superadmin_protected(client, db):
    make_user(db, "super_admin", "root")
    sa2 = make_user(db, "super_admin", "root2")
    login(client, "root")
    # root can disable root2 while root remains
    assert client.patch(f"/api/v1/users/{sa2.id}", json={"is_active": False}).status_code == 200
    # now root is the last active super admin; root2 (inactive) can be re-enabled; demoting root impossible (self)
    client.post("/api/v1/auth/logout")
    from app.models import User
    from app.services import users as svc

    actor = db.query(User).filter_by(username="root2").one()
    target = db.query(User).filter_by(username="root").one()
    import pytest

    from app.core.errors import AppError

    with pytest.raises(AppError) as e:
        svc.update_user(db, actor, target, is_active=False)
    assert e.value.status_code == 409
    with pytest.raises(AppError):
        svc.update_user(db, actor, target, role="admin")
    with pytest.raises(AppError):
        svc.delete_user(db, actor, target)


def test_role_change_revokes_sessions(client, db):
    make_user(db, "super_admin", "root")
    u = make_user(db, "admin", "victim")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="https://testserver") as c2:
        login(c2, "victim")
        assert c2.get("/api/v1/jobs").status_code == 200
        login(client, "root")
        assert client.patch(f"/api/v1/users/{u.id}", json={"role": "viewer"}).status_code == 200
        assert c2.get("/api/v1/jobs").status_code == 401


def test_user_activity_and_last_login(client, db):
    make_user(db, "super_admin", "root")
    u = make_user(db, "viewer", "watcher")
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="https://testserver") as c2:
        login(c2, "watcher", PASSWORD)
    login(client, "root")
    d = client.get(f"/api/v1/users/{u.id}").json()
    assert d["last_login_at"] is not None
    acts = client.get(f"/api/v1/users/{u.id}/activity").json()
    assert any(a["action"] == "auth.login" for a in acts)
