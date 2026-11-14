from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import not_found
from app.core.permissions import P
from app.db.session import get_db
from app.models import Alert, AlertRule, Switch, SwitchEvent, User
from app.services import alerts as svc
from app.services import audit

router = APIRouter(tags=["alerts"])


class RuleUpdate(BaseModel):
    enabled: bool | None = None
    severity: str | None = Field(default=None, pattern="^(info|warning|major|critical)$")
    threshold: float | None = Field(default=None, ge=0, le=100000)
    notify_email: bool | None = None
    recipients: list[EmailStr] | None = None


def alert_out(a: Alert, hostname: str | None) -> dict:
    return {"id": a.id, "type": a.type, "severity": a.severity, "status": a.status, "message": a.message,
            "switch_id": a.switch_id, "hostname": hostname, "port_name": a.port_name, "first_seen": a.first_seen,
            "last_seen": a.last_seen, "occurrences": a.occurrences, "acknowledged_at": a.acknowledged_at,
            "resolved_at": a.resolved_at, "details": a.details}


@router.get("/alerts")
def list_alerts(status: str | None = "open", severity: str | None = None, switch_id: int | None = None,
                page: int = Query(1, ge=1), page_size: int = Query(100, le=500),
                user: User = Depends(require(P.ALERT_VIEW)), db: Session = Depends(get_db)) -> dict:
    stmt = select(Alert, Switch.hostname).outerjoin(Switch, Switch.id == Alert.switch_id)
    if status == "open":
        stmt = stmt.where(Alert.status != "resolved")
    elif status:
        stmt = stmt.where(Alert.status == status)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if switch_id:
        stmt = stmt.where(Alert.switch_id == switch_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Alert.last_seen.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    counts = dict(db.execute(select(Alert.severity, func.count()).where(Alert.status == "active").group_by(Alert.severity)).all())
    return {"items": [alert_out(a, h) for a, h in rows], "total": total, "active_by_severity": counts}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: int, user: User = Depends(require(P.ALERT_ACK)), db: Session = Depends(get_db)) -> dict:
    a = db.get(Alert, alert_id)
    if a is None:
        raise not_found("Alert")
    svc.acknowledge(db, a, user)
    audit.record(db, action="alert.ack", actor=user, target_type="alert", target_id=a.id, switch_id=a.switch_id)
    db.commit()
    return alert_out(a, None)


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, user: User = Depends(require(P.ALERT_RULE_MANAGE)), db: Session = Depends(get_db)) -> dict:
    a = db.get(Alert, alert_id)
    if a is None:
        raise not_found("Alert")
    from app.db.base import utcnow

    a.status, a.resolved_at = "resolved", utcnow()
    audit.record(db, action="alert.resolve", actor=user, target_type="alert", target_id=a.id, switch_id=a.switch_id)
    db.commit()
    return alert_out(a, None)


@router.get("/alert-rules")
def rules(user: User = Depends(require(P.ALERT_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": r.id, "type": r.type, "name": r.name, "enabled": r.enabled, "severity": r.severity,
             "threshold": r.threshold, "notify_email": r.notify_email, "recipients": r.recipients}
            for r in db.execute(select(AlertRule).order_by(AlertRule.id)).scalars()]


@router.patch("/alert-rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, user: User = Depends(require(P.ALERT_RULE_MANAGE)),
                db: Session = Depends(get_db)) -> dict:
    r = db.get(AlertRule, rule_id)
    if r is None:
        raise not_found("Alert rule")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(r, k, [str(x) for x in v] if k == "recipients" else v)
    audit.record(db, action="alert_rule.update", actor=user, target_type="alert_rule", target_id=r.id,
                 details={k: (v if k != "recipients" else len(v or [])) for k, v in data.items()})
    db.commit()
    return {"id": r.id, "type": r.type, "name": r.name, "enabled": r.enabled, "severity": r.severity,
            "threshold": r.threshold, "notify_email": r.notify_email, "recipients": r.recipients}


@router.get("/events")
def events(switch_id: int | None = None, severity: str | None = None, type_prefix: str | None = None,
           page: int = Query(1, ge=1), page_size: int = Query(100, le=500),
           user: User = Depends(require(P.EVENT_VIEW)), db: Session = Depends(get_db)) -> dict:
    stmt = select(SwitchEvent, Switch.hostname).outerjoin(Switch, Switch.id == SwitchEvent.switch_id)
    if switch_id:
        stmt = stmt.where(SwitchEvent.switch_id == switch_id)
    if severity:
        stmt = stmt.where(SwitchEvent.severity == severity)
    if type_prefix:
        stmt = stmt.where(SwitchEvent.type.like(f"{type_prefix}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(SwitchEvent.ts.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [{"id": e.id, "ts": e.ts, "severity": e.severity, "type": e.type, "message": e.message,
                       "switch_id": e.switch_id, "hostname": h, "port_name": e.port_name} for e, h in rows],
            "total": total}
