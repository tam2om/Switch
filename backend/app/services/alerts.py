"""Alert lifecycle: raise (deduplicated), resolve, acknowledge, and queue e-mail notifications."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.models import Alert, AlertRule, Notification, Switch, SwitchEvent, User

log = logging.getLogger(__name__)
SEVERITIES = ("info", "warning", "major", "critical")


def event(db: Session, *, type: str, message: str, severity: str = "info", switch_id: int | None = None,
          port_name: str | None = None, details: dict | None = None) -> SwitchEvent:
    e = SwitchEvent(type=type, message=message, severity=severity, switch_id=switch_id, port_name=port_name,
                    details=details or {})
    db.add(e)
    return e


def _rule(db: Session, type: str) -> AlertRule | None:
    return db.execute(select(AlertRule).where(AlertRule.type == type)).scalar_one_or_none()


def raise_alert(db: Session, *, type: str, message: str, switch: Switch | None = None, port_name: str | None = None,
                details: dict | None = None, dedup_suffix: str = "", severity: str | None = None) -> Alert | None:
    rule = _rule(db, type)
    if rule is not None and not rule.enabled:
        return None
    dedup = f"{type}:{switch.id if switch else '-'}:{port_name or '-'}{(':' + dedup_suffix) if dedup_suffix else ''}"
    existing = db.execute(select(Alert).where(Alert.dedup_key == dedup, Alert.status != "resolved")).scalar_one_or_none()
    now = utcnow()
    if existing:
        existing.last_seen = now
        existing.occurrences += 1
        existing.message = message
        if details:
            existing.details = details
        return existing
    sev = severity or (rule.severity if rule else "warning")
    a = Alert(rule_id=rule.id if rule else None, type=type, severity=sev, switch_id=switch.id if switch else None,
              port_name=port_name, dedup_key=dedup, message=message, details=details or {}, first_seen=now,
              last_seen=now)
    db.add(a)
    db.flush()
    event(db, type=f"alert.{type}", message=message, severity=sev, switch_id=switch.id if switch else None,
          port_name=port_name, details={"alert_id": a.id})
    if rule and rule.notify_email and rule.recipients:
        for rcpt in rule.recipients:
            db.add(Notification(alert_id=a.id, channel="email", recipient=rcpt,
                                subject=f"[ANM {sev.upper()}] {message}"[:255]))
    return a


def resolve(db: Session, *, type: str, switch: Switch | None = None, port_name: str | None = None,
            dedup_suffix: str = "", message: str | None = None) -> Alert | None:
    dedup = f"{type}:{switch.id if switch else '-'}:{port_name or '-'}{(':' + dedup_suffix) if dedup_suffix else ''}"
    a = db.execute(select(Alert).where(Alert.dedup_key == dedup, Alert.status != "resolved")).scalar_one_or_none()
    if a:
        a.status = "resolved"
        a.resolved_at = utcnow()
        event(db, type=f"alert_resolved.{type}", message=message or f"Resolved: {a.message}", severity="info",
              switch_id=a.switch_id, port_name=port_name)
    return a


def acknowledge(db: Session, alert: Alert, user: User) -> Alert:
    if alert.status == "active":
        alert.status = "acknowledged"
        alert.acknowledged_by_id = user.id
        alert.acknowledged_at = utcnow()
    return alert


def send_pending_notifications(db: Session, limit: int = 50) -> dict:
    s = get_settings()
    rows = db.execute(select(Notification).where(Notification.status == "pending").limit(limit)).scalars().all()
    if not rows:
        return {"sent": 0, "failed": 0}
    if not s.smtp_host:
        for n in rows:
            n.status = "failed"
            n.error = "SMTP is not configured"
        return {"sent": 0, "failed": len(rows)}
    sent = failed = 0
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
            if s.smtp_starttls:
                smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            for n in rows:
                msg = EmailMessage()
                msg["From"] = s.smtp_from
                msg["To"] = n.recipient
                msg["Subject"] = n.subject
                alert = db.get(Alert, n.alert_id) if n.alert_id else None
                msg.set_content(f"{n.subject}\n\n{alert.message if alert else ''}\n\nAruba Network Manager")
                try:
                    smtp.send_message(msg)
                    n.status = "sent"
                    n.sent_at = utcnow()
                    sent += 1
                except smtplib.SMTPException as exc:
                    n.status = "failed"
                    n.error = str(exc)[:500]
                    failed += 1
    except (OSError, smtplib.SMTPException) as exc:
        for n in rows:
            if n.status == "pending":
                n.status = "failed"
                n.error = f"SMTP connection failed: {exc.__class__.__name__}"
                failed += 1
    return {"sent": sent, "failed": failed}
