"""Hash-chained, append-only audit logging.

Every row's hash = sha256(prev_hash + canonical JSON of the row content). verify_chain() detects any modified,
inserted or deleted row. A PostgreSQL advisory transaction lock serialises writers so the chain stays linear.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.redact import redact
from app.db.base import utcnow
from app.models import AuditLog, User

_AUDIT_LOCK = 774411  # arbitrary advisory-lock key


def _canonical(row: AuditLog) -> str:
    payload = {
        "ts": row.ts.isoformat(),
        "category": row.category,
        "action": row.action,
        "result": row.result,
        "actor_user_id": row.actor_user_id,
        "actor_username": row.actor_username,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "switch_id": row.switch_id,
        "ip": row.ip,
        "details": row.details,
    }
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _compute_hash(prev_hash: str, row: AuditLog) -> str:
    return hashlib.sha256((prev_hash + _canonical(row)).encode()).hexdigest()


def record(
    db: Session,
    *,
    action: str,
    category: str = "operational",
    actor: User | None = None,
    actor_name: str | None = None,
    result: str = "success",
    target_type: str | None = None,
    target_id: Any = None,
    switch_id: int | None = None,
    ip: str | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Append an audit record. Caller commits (so the record is atomic with the audited change)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _AUDIT_LOCK})
    prev = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar_one_or_none() or ""
    ts: datetime = utcnow().replace(microsecond=(utcnow().microsecond // 1000) * 1000)
    row = AuditLog(
        ts=ts,
        category=category,
        action=action,
        result=result,
        actor_user_id=actor.id if actor else None,
        actor_username=actor.username if actor else (actor_name or "system"),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        switch_id=switch_id,
        ip=ip,
        details=redact(details or {}),
        prev_hash=prev,
    )
    row.hash = _compute_hash(prev, row)
    db.add(row)
    db.flush()
    return row


def record_independent(**kwargs: Any) -> None:
    """Write an audit record in its own transaction (for failures where the main transaction rolls back)."""
    from app.db.session import db_session

    with db_session() as db:
        actor = kwargs.pop("actor", None)
        if actor is not None:
            kwargs["actor_name"] = actor.username
            kwargs["details"] = {**(kwargs.get("details") or {})}
            record(db, actor=db.get(User, actor.id), **kwargs)
        else:
            record(db, **kwargs)


def verify_chain(db: Session, limit: int | None = None) -> dict:
    q = select(AuditLog).order_by(AuditLog.id)
    prev = ""
    count = 0
    for row in db.execute(q).scalars():
        # Microsecond precision is truncated to ms at write time, matching the stored value.
        if row.prev_hash != prev:
            return {"valid": False, "broken_at": row.id, "reason": "prev_hash mismatch", "checked": count}
        if _compute_hash(prev, row) != row.hash:
            return {"valid": False, "broken_at": row.id, "reason": "content hash mismatch", "checked": count}
        prev = row.hash
        count += 1
        if limit and count >= limit:
            break
    return {"valid": True, "checked": count}
