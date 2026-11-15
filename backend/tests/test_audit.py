import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog
from app.services import audit
from tests.conftest import login, make_user


def test_chain_valid_and_detects_tampering(db):
    for i in range(5):
        audit.record(db, action=f"test.{i}", details={"i": i, "password": "secret"})
    db.commit()
    assert audit.verify_chain(db)["valid"]
    rows = db.query(AuditLog).order_by(AuditLog.id).all()
    assert rows[0].details["password"] == "********"  # masked
    # Database trigger blocks UPDATE/DELETE outright.
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE audit_logs SET action='forged' WHERE id = :i"), {"i": rows[2].id})
        db.commit()
    db.rollback()
    with pytest.raises(DBAPIError):
        db.execute(text("DELETE FROM audit_logs WHERE id = :i"), {"i": rows[2].id})
        db.commit()
    db.rollback()
    # Even with the trigger bypassed by a DB superuser, verification detects the edit.
    db.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_protect"))
    db.execute(text("UPDATE audit_logs SET action='forged' WHERE id = :i"), {"i": rows[2].id})
    db.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_protect"))
    db.commit()
    res = audit.verify_chain(db)
    assert res["valid"] is False and res["broken_at"] == rows[2].id


def test_retention_delete_allowed_only_in_retention_mode(db):
    audit.record(db, action="old")
    audit.record(db, action="new")
    db.commit()
    db.execute(text("SET LOCAL anm.audit_retention = 'on'"))
    db.execute(text("DELETE FROM audit_logs WHERE action='old'"))
    db.commit()
    assert audit.verify_chain(db)["valid"]


def test_audit_api_scoping(client, db):
    make_user(db, "admin", "ops")
    make_user(db, "super_admin", "boss")
    audit.record(db, action="user.create", category="security")
    audit.record(db, action="switch.create", category="operational")
    db.commit()
    login(client, "ops")
    cats = {i["category"] for i in client.get("/api/v1/audit").json()["items"]}
    assert cats == {"operational"}
    assert client.get("/api/v1/audit/verify").status_code == 403
    client.post("/api/v1/auth/logout")
    login(client, "boss")
    cats = {i["category"] for i in client.get("/api/v1/audit").json()["items"]}
    assert {"security", "auth", "operational"} <= cats
    assert client.get("/api/v1/audit/verify").json()["valid"]
    r = client.get("/api/v1/audit/export")
    assert r.status_code == 200 and "user.create" in r.text
