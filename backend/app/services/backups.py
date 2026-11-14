"""Configuration backups: capture, encrypt, verify, diff, retention and drift detection."""

from __future__ import annotations

import difflib
import logging
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import CryptoError, sha256_hex
from app.core.errors import AppError, not_found
from app.db.base import utcnow
from app.drivers.base import SwitchDriver
from app.models import ChangeJob, ChangeJobResult, ConfigBackup, ConfigDiff, Switch, User
from app.services import alerts, audit, storage
from app.services import settings as sysset

log = logging.getLogger(__name__)


def latest(db: Session, switch_id: int) -> ConfigBackup | None:
    return db.execute(select(ConfigBackup).where(ConfigBackup.switch_id == switch_id)
                      .order_by(ConfigBackup.created_at.desc(), ConfigBackup.id.desc()).limit(1)).scalar_one_or_none()


def take_backup(db: Session, sw: Switch, drv: SwitchDriver, *, trigger: str, user: User | None = None,
                job_id: int | None = None, note: str = "", dedupe: bool = False) -> ConfigBackup:
    cfg = drv.get_running_config()
    data = cfg.text.encode()
    digest = sha256_hex(data)
    prev = latest(db, sw.id)
    if dedupe and prev is not None and prev.sha256 == digest:
        prev.verified_at = utcnow()
        return prev
    key = f"switches/{sw.id}/{utcnow():%Y/%m/%d}/{uuid.uuid4().hex}.cfg.enc"
    size = storage.put_encrypted(key, data)
    b = ConfigBackup(switch_id=sw.id, trigger=trigger, storage_key=key, size_bytes=size, sha256=digest, encrypted=True,
                     source="simulator" if sw.is_simulated else cfg.source, created_by_id=user.id if user else None,
                     job_id=job_id, note=note[:255], firmware=sw.firmware)
    db.add(b)
    db.flush()
    verify(db, b)
    sw.last_config_sha256 = digest
    if prev is not None and prev.sha256 != digest:
        added, removed = _count_changes(read_text(prev), cfg.text)
        expected = trigger in ("pre_change", "post_change") or _app_changed_since(db, sw.id, prev)
        db.add(ConfigDiff(switch_id=sw.id, from_backup_id=prev.id, to_backup_id=b.id, added_lines=added,
                          removed_lines=removed, expected=expected))
        if not expected:
            alerts.raise_alert(db, type="unexpected_config_change", switch=sw,
                               message=f"Configuration of {sw.hostname} changed outside this application "
                                       f"(+{added}/-{removed} lines)",
                               details={"from_backup": prev.id, "to_backup": b.id}, dedup_suffix=str(b.id))
    audit.record(db, action="backup.create", category="operational", actor=user, target_type="switch",
                 target_id=sw.id, switch_id=sw.id, details={"backup_id": b.id, "trigger": trigger, "sha256": digest})
    return b


def _app_changed_since(db: Session, switch_id: int, prev: ConfigBackup) -> bool:
    """True if a change job by this application touched the switch after the previous backup."""
    row = db.execute(select(ChangeJobResult.id).join(ChangeJob).where(
        ChangeJobResult.switch_id == switch_id, ChangeJobResult.status.in_(("success", "verify_failed", "failed")),
        ChangeJobResult.finished_at >= prev.created_at).limit(1)).first()
    return row is not None


def _count_changes(a: str, b: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def read_text(b: ConfigBackup) -> str:
    try:
        data = storage.get_decrypted(b.storage_key)
    except (CryptoError, FileNotFoundError, OSError) as exc:
        raise AppError(500, "backup_unreadable", f"Backup {b.id} could not be read or decrypted") from exc
    if sha256_hex(data) != b.sha256:
        raise AppError(500, "backup_corrupt", f"Backup {b.id} failed checksum verification")
    return data.decode()


def verify(db: Session, b: ConfigBackup) -> bool:
    """Re-read from storage, decrypt and compare the checksum."""
    try:
        read_text(b)
        b.verify_status = "verified"
        ok = True
    except AppError:
        b.verify_status = "failed"
        ok = False
    b.verified_at = utcnow()
    return ok


def diff(db: Session, a_id: int, b_id: int) -> dict:
    a, b = db.get(ConfigBackup, a_id), db.get(ConfigBackup, b_id)
    if a is None or b is None:
        raise not_found("Backup")
    ta, tb = read_text(a), read_text(b)
    lines = list(difflib.unified_diff(ta.splitlines(), tb.splitlines(), fromfile=f"backup-{a.id}",
                                      tofile=f"backup-{b.id}", lineterm="", n=3))
    added, removed = _count_changes(ta, tb)
    return {"from": a.id, "to": b.id, "added": added, "removed": removed, "diff": "\n".join(lines),
            "identical": a.sha256 == b.sha256}


def apply_retention(db: Session) -> int:
    keep = int(sysset.get(db, "backups.retention_count"))
    removed = 0
    cutoff_pre = utcnow() - timedelta(days=90)
    for (switch_id,) in db.execute(select(ConfigBackup.switch_id).distinct()).all():
        rows = db.execute(select(ConfigBackup).where(ConfigBackup.switch_id == switch_id)
                          .order_by(ConfigBackup.created_at.desc())).scalars().all()
        for b in rows[keep:]:
            if b.trigger == "pre_change" and b.created_at > cutoff_pre:
                continue
            if b.restore_tested:
                continue
            referenced = db.execute(select(ConfigDiff.id).where(
                (ConfigDiff.from_backup_id == b.id) | (ConfigDiff.to_backup_id == b.id))).first()
            try:
                storage.get_store().delete(b.storage_key)
            except Exception:  # noqa: BLE001
                log.warning("could not delete backup object %s", b.storage_key)
                continue
            if referenced:
                db.query(ConfigDiff).filter((ConfigDiff.from_backup_id == b.id) | (ConfigDiff.to_backup_id == b.id)).delete()
            db.delete(b)
            removed += 1
    return removed
