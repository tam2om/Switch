from datetime import timedelta

import pyotp

from app.db.base import utcnow
from app.models import UserSession
from tests.conftest import PASSWORD, login, make_user


def test_login_logout_and_me(client, db):
    make_user(db, "viewer", "vera")
    r = client.post("/api/v1/auth/login", json={"username": "vera", "password": PASSWORD})
    assert r.status_code == 200
    cookie = r.headers.get_list("set-cookie")
    assert any("anm_session=" in c and "HttpOnly" in c and "Secure" in c and "SameSite=strict" in c for c in cookie)
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "viewer" and "dashboard.view" in me["permissions"] and "port.manage" not in me["permissions"]
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_bad_password_generic_error_and_lockout(client, db):
    make_user(db, "monitor", "mona")
    for _ in range(5):
        r = client.post("/api/v1/auth/login", json={"username": "mona", "password": "wrong-password"})
        assert r.status_code == 401
        assert r.json()["detail"]["message"] == "Invalid username or password"
    r = client.post("/api/v1/auth/login", json={"username": "mona", "password": PASSWORD})
    assert r.status_code == 423  # locked even with correct password
    r = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401 and r.json()["detail"]["message"] == "Invalid username or password"


def test_rate_limit(client, db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_rate_per_minute", 3)
    for _ in range(3):
        client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"})
    r = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 429


def test_csrf_required_for_mutations(client, db):
    make_user(db, "super_admin", "root1")
    login(client, "root1")
    token = client.headers.pop("X-CSRF-Token")
    r = client.post("/api/v1/sites", json={"name": "HQ"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "csrf_failed"
    client.headers["X-CSRF-Token"] = "wrong"
    assert client.post("/api/v1/sites", json={"name": "HQ"}).status_code == 403
    client.headers["X-CSRF-Token"] = token
    assert client.post("/api/v1/sites", json={"name": "HQ"}).status_code == 201


def test_session_idle_expiry(client, db):
    make_user(db, "viewer", "idle")
    login(client, "idle")
    s = db.query(UserSession).one()
    s.last_seen_at = utcnow() - timedelta(minutes=31)
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    db.refresh(s)
    assert s.revoked_at is not None


def test_session_absolute_expiry(client, db):
    make_user(db, "viewer", "abs")
    login(client, "abs")
    s = db.query(UserSession).one()
    s.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_disabled_user_sessions_rejected(client, db):
    u = make_user(db, "viewer", "gone")
    login(client, "gone")
    u.is_active = False
    db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_must_change_password_blocks_api(client, db):
    make_user(db, "admin", "newbie", must_change_password=True)
    login(client, "newbie")
    r = client.get("/api/v1/switches")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "password_change_required"
    assert client.get("/api/v1/auth/me").status_code == 200
    r = client.post("/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "Brand-New-Pass-77"})
    assert r.status_code == 200
    assert client.get("/api/v1/switches").status_code == 200


def test_totp_mfa_flow(client, db):
    make_user(db, "admin", "mfa-user")
    login(client, "mfa-user")
    enroll = client.post("/api/v1/auth/mfa/enroll").json()
    totp = pyotp.TOTP(enroll["secret"])
    assert client.post("/api/v1/auth/mfa/confirm", json={"code": "000000"}).status_code == 400
    assert client.post("/api/v1/auth/mfa/confirm", json={"code": totp.now()}).status_code == 200
    client.post("/api/v1/auth/logout")
    res = login(client, "mfa-user")
    assert res["mfa_required"] is True and res["user"] is None
    r = client.get("/api/v1/switches")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "mfa_required"
    assert client.post("/api/v1/auth/mfa/verify", json={"code": "123456"}).status_code == 401
    assert client.post("/api/v1/auth/mfa/verify", json={"code": totp.now()}).status_code == 200
    assert client.get("/api/v1/switches").status_code == 200


def test_password_reset_token_flow(client, db):
    make_user(db, "super_admin", "boss")
    target = make_user(db, "viewer", "forgetful")
    login(client, "boss")
    tok = client.post(f"/api/v1/users/{target.id}/reset-token").json()["token"]
    client.post("/api/v1/auth/logout")
    client.headers.pop("X-CSRF-Token", None)
    assert client.post("/api/v1/auth/reset", json={"token": tok, "new_password": "weak"}).status_code == 400
    assert client.post("/api/v1/auth/reset", json={"token": tok, "new_password": "Recovered-Pass-42"}).status_code == 200
    assert client.post("/api/v1/auth/reset", json={"token": tok, "new_password": "Recovered-Pass-43"}).status_code == 400
    login(client, "forgetful", "Recovered-Pass-42")


def test_network_restriction(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import get_settings
    from app.main import app

    monkeypatch.setattr(get_settings(), "environment", "production")
    with TestClient(app, base_url="https://testserver") as c:
        r = c.get("/api/v1/setup/status")  # peer "testclient" is not an IP -> denied outside tests
        assert r.status_code == 403 and r.json()["detail"]["code"] == "network_denied"
        assert c.get("/health").status_code == 200


def test_x_forwarded_for_only_trusted_from_proxy():
    from starlette.requests import Request

    from app.api.deps import client_ip

    def req(peer, xff):
        return Request({"type": "http", "client": (peer, 1234), "headers": [(b"x-forwarded-for", xff.encode())]})

    assert client_ip(req("203.0.113.5", "10.0.0.5")) == "203.0.113.5"  # untrusted peer: header ignored
    assert client_ip(req("127.0.0.1", "203.0.113.9, 10.1.1.1")) == "10.1.1.1"
