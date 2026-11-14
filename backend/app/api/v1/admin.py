"""Audit log, system settings, device credentials, polling schedule, system health, capability matrix."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import require, require_any
from app.core.config import get_settings
from app.core.errors import bad_request, forbidden, not_found
from app.core.permissions import P, has_permission
from app.db.base import utcnow
from app.db.session import get_db
from app.drivers.aruba.aos_switch.capabilities import registry_matrix
from app.models import AuditLog, PollingJob, Switch, SwitchCredential, User
from app.services import audit, credentials
from app.services import settings as sysset

router = APIRouter(tags=["administration"])


# ------------------------------------------------------------------ audit

@router.get("/audit")
def audit_log(category: str | None = None, action: str | None = None, actor: str | None = None,
              switch_id: int | None = None, since: datetime | None = None, until: datetime | None = None,
              page: int = Query(1, ge=1), page_size: int = Query(100, le=500),
              user: User = Depends(require_any(P.AUDIT_VIEW_ALL, P.AUDIT_VIEW_OPERATIONAL)),
              db: Session = Depends(get_db)) -> dict:
    stmt = select(AuditLog)
    if not has_permission(user.role, P.AUDIT_VIEW_ALL):
        stmt = stmt.where(AuditLog.category == "operational")
    if category:
        stmt = stmt.where(AuditLog.category == category)
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if actor:
        stmt = stmt.where(func.lower(AuditLog.actor_username) == actor.lower())
    if switch_id:
        stmt = stmt.where(AuditLog.switch_id == switch_id)
    if since:
        stmt = stmt.where(AuditLog.ts >= since)
    if until:
        stmt = stmt.where(AuditLog.ts <= until)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"items": [{"id": r.id, "ts": r.ts, "category": r.category, "action": r.action, "result": r.result,
                       "actor": r.actor_username, "target_type": r.target_type, "target_id": r.target_id,
                       "switch_id": r.switch_id, "ip": r.ip, "details": r.details} for r in rows], "total": total}


@router.get("/audit/verify")
def audit_verify(user: User = Depends(require(P.AUDIT_VIEW_ALL)), db: Session = Depends(get_db)) -> dict:
    return audit.verify_chain(db)


@router.get("/audit/export")
def audit_export(user: User = Depends(require(P.AUDIT_VIEW_ALL)), db: Session = Depends(get_db)) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "ts", "category", "action", "result", "actor", "target_type", "target_id", "switch_id", "ip",
                "hash"])
    for r in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        w.writerow([r.id, r.ts.isoformat(), r.category, r.action, r.result, r.actor_username, r.target_type or "",
                    r.target_id or "", r.switch_id or "", r.ip or "", r.hash])
    audit.record(db, action="audit.export", category="security", actor=user)
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="anm-audit.csv"'})


# ------------------------------------------------------------------ settings

class SettingIn(BaseModel):
    value: Any


@router.get("/settings")
def get_settings_list(user: User = Depends(require(P.SETTINGS_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    out = sysset.all_settings(db)
    for s in out:
        s["editable"] = has_permission(user.role, P.SETTINGS_MANAGE) or (
            s["category"] == "operational" and has_permission(user.role, P.OPERATIONAL_SETTINGS_MANAGE))
    return out


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, user: User = Depends(require(P.SETTINGS_VIEW)),
                db: Session = Depends(get_db)) -> dict:
    if key not in sysset.DEFAULTS:
        raise not_found("Setting")
    cat = sysset.category(key)
    if cat == "security" and not has_permission(user.role, P.SETTINGS_MANAGE):
        raise forbidden("Only a Super Admin can change security settings")
    if cat == "operational" and not has_permission(user.role, P.OPERATIONAL_SETTINGS_MANAGE):
        raise forbidden()
    old = sysset.get(db, key)
    try:
        sysset.set_value(db, key, body.value, user.id)
    except ValueError as exc:
        raise bad_request(str(exc), "invalid_setting") from exc
    audit.record(db, action="settings.update", category="security" if cat == "security" else "operational",
                 actor=user, target_type="setting", target_id=key, details={"old": old, "new": body.value})
    db.commit()
    return {"key": key, "value": sysset.get(db, key)}


# ------------------------------------------------------------------ credentials

class CredentialIn(BaseModel):
    switch_id: int | None = None
    kind: str = Field(pattern="^(snmpv3|rest|ssh)$")
    purpose: str = Field(pattern="^(monitor|config)$")
    username: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=64)
    password: str | None = Field(default=None, max_length=128)
    auth_password: str | None = Field(default=None, max_length=128)
    priv_password: str | None = Field(default=None, max_length=128)
    auth_protocol: str = Field(default="sha", pattern="^(sha|sha256|sha512)$")
    priv_protocol: str = Field(default="aes", pattern="^(aes|aes192|aes256)$")
    port: int = Field(default=22, ge=1, le=65535)


@router.get("/credentials")
def list_credentials(user: User = Depends(require(P.CREDENTIAL_MANAGE)), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(SwitchCredential).order_by(SwitchCredential.switch_id.nulls_first(),
                                                        SwitchCredential.kind)).scalars().all()
    return [credentials.public_view(c) for c in rows]


@router.put("/credentials")
def upsert_credential(body: CredentialIn, user: User = Depends(require(P.CREDENTIAL_MANAGE)),
                      db: Session = Depends(get_db)) -> dict:
    if body.switch_id is not None and db.get(Switch, body.switch_id) is None:
        raise not_found("Switch")
    if body.kind == "snmpv3":
        if body.purpose != "monitor":
            raise bad_request("SNMPv3 is used for monitoring only; the application never writes via SNMP")
        if not body.auth_password or not body.priv_password or len(body.auth_password) < 8 or len(body.priv_password) < 8:
            raise bad_request("SNMPv3 requires authPriv with passphrases of at least 8 characters")
        secrets = {"auth_password": body.auth_password, "priv_password": body.priv_password}
        params = {"auth_protocol": body.auth_protocol, "priv_protocol": body.priv_protocol}
    else:
        if not body.password:
            raise bad_request("Password is required")
        secrets = {"password": body.password}
        params = {"port": body.port} if body.kind == "ssh" else {}
    try:
        cred = credentials.upsert(db, switch_id=body.switch_id, kind=body.kind, purpose=body.purpose,
                                  username=body.username, secrets=secrets, params=params, name=body.name)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    audit.record(db, action="credential.upsert", category="security", actor=user, target_type="credential",
                 target_id=cred.id, switch_id=body.switch_id,
                 details={"kind": body.kind, "purpose": body.purpose, "username": body.username})
    db.commit()
    return credentials.public_view(cred)


@router.delete("/credentials/{cred_id}")
def delete_credential(cred_id: int, user: User = Depends(require(P.CREDENTIAL_MANAGE)), db: Session = Depends(get_db)) -> dict:
    c = db.get(SwitchCredential, cred_id)
    if c is None:
        raise not_found("Credential")
    audit.record(db, action="credential.delete", category="security", actor=user, target_type="credential",
                 target_id=c.id, switch_id=c.switch_id, details={"kind": c.kind, "purpose": c.purpose})
    db.delete(c)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ polling + system health

@router.get("/polling")
def polling_jobs(user: User = Depends(require(P.SYSTEM_HEALTH_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"category": j.category, "interval_seconds": j.interval_seconds, "enabled": j.enabled,
             "last_run_at": j.last_run_at, "last_duration_ms": j.last_duration_ms, "last_status": j.last_status,
             "last_error": j.last_error, "switches_polled": j.switches_polled, "switches_failed": j.switches_failed}
            for j in db.execute(select(PollingJob).order_by(PollingJob.id)).scalars()]


@router.patch("/polling/{category}")
def toggle_polling(category: str, body: dict, user: User = Depends(require(P.OPERATIONAL_SETTINGS_MANAGE)),
                   db: Session = Depends(get_db)) -> dict:
    j = db.execute(select(PollingJob).where(PollingJob.category == category)).scalar_one_or_none()
    if j is None:
        raise not_found("Polling category")
    if not isinstance(body.get("enabled"), bool):
        raise bad_request("enabled must be true or false")
    j.enabled = body["enabled"]
    audit.record(db, action="polling.toggle", actor=user, target_type="polling", target_id=category,
                 details={"enabled": j.enabled})
    db.commit()
    return {"category": category, "enabled": j.enabled}


@router.get("/system/health")
def system_health(user: User = Depends(require(P.SYSTEM_HEALTH_VIEW)), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    out: dict[str, Any] = {"time": utcnow(), "environment": s.environment, "simulator_enabled": s.simulator_enabled}
    try:
        row = db.execute(text("SELECT version(), pg_database_size(current_database())")).one()
        ts = db.execute(text("SELECT extversion FROM pg_extension WHERE extname='timescaledb'")).scalar()
        rev = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        out["database"] = {"ok": True, "version": row[0].split(",")[0], "size_bytes": row[1], "timescaledb": ts,
                           "migration": rev}
    except Exception as exc:  # noqa: BLE001
        out["database"] = {"ok": False, "error": exc.__class__.__name__}
    try:
        import redis

        r = redis.Redis.from_url(s.redis_url, socket_timeout=2)
        info = r.info("server")
        out["redis"] = {"ok": True, "version": info.get("redis_version"),
                        "queues": {q: r.llen(q) for q in ("default", "polling", "changes")}}
    except Exception as exc:  # noqa: BLE001
        out["redis"] = {"ok": False, "error": exc.__class__.__name__}
    try:
        from app.services.storage import get_store

        out["storage"] = get_store().health()
    except Exception as exc:  # noqa: BLE001
        out["storage"] = {"ok": False, "error": exc.__class__.__name__}
    try:
        from app.workers.celery_app import celery

        replies = celery.control.inspect(timeout=1.5).ping() or {}
        active = celery.control.inspect(timeout=1.5).active() or {}
        out["workers"] = {"ok": bool(replies), "count": len(replies),
                          "nodes": [{"name": k, "active_tasks": len(active.get(k, []))} for k in replies]}
    except Exception as exc:  # noqa: BLE001
        out["workers"] = {"ok": False, "error": exc.__class__.__name__, "count": 0, "nodes": []}
    out["polling"] = polling_jobs(user, db)
    out["switches"] = dict(db.execute(select(Switch.status, func.count()).group_by(Switch.status)).all())
    return out


@router.get("/capabilities/matrix")
def capability_matrix(user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> dict:
    observed: dict[str, dict[str, int]] = {}
    for sw in db.execute(select(Switch).where(Switch.is_simulated.is_(False))).unique().scalars():
        for key, ok in ((sw.capabilities or {}).get("resources") or {}).items():
            d = observed.setdefault(key, {"ok": 0, "failed": 0})
            d["ok" if ok else "failed"] += 1
    return {"registry": registry_matrix(), "observed_on_real_switches": observed}
