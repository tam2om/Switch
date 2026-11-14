from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import not_found
from app.core.permissions import P
from app.db.session import get_db
from app.models import ConfigBackup, ConfigDiff, Switch, User
from app.services import audit
from app.services import backups as svc

router = APIRouter(prefix="/backups", tags=["backups"])


def backup_out(b: ConfigBackup, hostname: str | None = None) -> dict:
    return {"id": b.id, "switch_id": b.switch_id, "hostname": hostname, "created_at": b.created_at,
            "trigger": b.trigger, "size_bytes": b.size_bytes, "sha256": b.sha256, "encrypted": b.encrypted,
            "source": b.source, "verify_status": b.verify_status, "verified_at": b.verified_at,
            "restore_tested": b.restore_tested, "restore_tested_at": b.restore_tested_at, "job_id": b.job_id,
            "note": b.note, "firmware": b.firmware}


@router.get("")
def list_backups(switch_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, le=200),
                 user: User = Depends(require(P.BACKUP_VIEW)), db: Session = Depends(get_db)) -> dict:
    stmt = select(ConfigBackup, Switch.hostname).join(Switch, Switch.id == ConfigBackup.switch_id)
    if switch_id:
        stmt = stmt.where(ConfigBackup.switch_id == switch_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(ConfigBackup.created_at.desc(), ConfigBackup.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [backup_out(b, h) for b, h in rows], "total": total, "page": page}


@router.get("/drift")
def drift(user: User = Depends(require(P.BACKUP_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(ConfigDiff, Switch.hostname).join(Switch, Switch.id == ConfigDiff.switch_id)
                      .order_by(ConfigDiff.created_at.desc()).limit(200)).all()
    return [{"id": d.id, "switch_id": d.switch_id, "hostname": h, "from_backup_id": d.from_backup_id,
             "to_backup_id": d.to_backup_id, "added": d.added_lines, "removed": d.removed_lines,
             "expected": d.expected, "created_at": d.created_at} for d, h in rows]


@router.get("/diff")
def diff(a: int, b: int, user: User = Depends(require(P.BACKUP_EXPORT)), db: Session = Depends(get_db)) -> dict:
    return svc.diff(db, a, b)


@router.get("/{backup_id}")
def get_backup(backup_id: int, user: User = Depends(require(P.BACKUP_VIEW)), db: Session = Depends(get_db)) -> dict:
    b = db.get(ConfigBackup, backup_id)
    if b is None:
        raise not_found("Backup")
    return backup_out(b)


@router.get("/{backup_id}/content", response_class=PlainTextResponse)
def content(backup_id: int, download: bool = False, user: User = Depends(require(P.BACKUP_EXPORT)),
            db: Session = Depends(get_db)) -> PlainTextResponse:
    b = db.get(ConfigBackup, backup_id)
    if b is None:
        raise not_found("Backup")
    text = svc.read_text(b)
    audit.record(db, action="backup.export" if download else "backup.view", category="security", actor=user,
                 target_type="backup", target_id=b.id, switch_id=b.switch_id)
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="switch-{b.switch_id}-backup-{b.id}.cfg"'} if download else {}
    return PlainTextResponse(text, headers=headers)


@router.post("/{backup_id}/verify")
def verify(backup_id: int, user: User = Depends(require(P.BACKUP_MANAGE)), db: Session = Depends(get_db)) -> dict:
    b = db.get(ConfigBackup, backup_id)
    if b is None:
        raise not_found("Backup")
    ok = svc.verify(db, b)
    audit.record(db, action="backup.verify", actor=user, target_type="backup", target_id=b.id, switch_id=b.switch_id,
                 result="success" if ok else "failure")
    db.commit()
    return backup_out(b)
