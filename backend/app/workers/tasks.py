"""Celery tasks: polling dispatch, change-job execution, scheduled backups, notifications and maintenance."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, text

from app.db.base import utcnow
from app.db.session import db_session
from app.models import ChangeJob, PollingJob, Switch, SystemSetting
from app.services import alerts, backups, polling
from app.services import settings as sysset
from app.workers.celery_app import celery

log = logging.getLogger(__name__)

SETTING_FOR = {
    "availability": "polling.availability_seconds", "counters": "polling.counters_seconds",
    "health": "polling.health_seconds", "poe": "polling.poe_seconds", "temperature": "polling.temperature_seconds",
    "mac": "polling.mac_seconds", "lldp": "polling.lldp_seconds", "inventory": "polling.inventory_seconds",
}


@celery.task(name="app.workers.tasks.poll_category")
def poll_category(category: str, switch_ids: list[int] | None = None) -> dict:
    return polling.run_category(category, switch_ids)


@celery.task(name="app.workers.tasks.execute_job")
def execute_job(job_id: int) -> dict:
    from app.services.jobs.engine import run_job

    return run_job(job_id)


@celery.task(name="app.workers.tasks.scheduler_tick")
def scheduler_tick() -> dict:
    """Dispatch polling categories whose interval elapsed; recover orphaned jobs; trigger daily backups."""
    dispatched = []
    now = utcnow()
    with db_session() as db:
        for job in db.execute(select(PollingJob)).scalars():
            interval = int(sysset.get(db, SETTING_FOR[job.category])) if job.category in SETTING_FOR \
                else job.interval_seconds
            job.interval_seconds = interval
            if not job.enabled:
                continue
            if job.last_run_at is None or (now - job.last_run_at).total_seconds() >= interval:
                job.last_run_at = now  # claim the slot before dispatch to avoid duplicates
                dispatched.append(job.category)
        # Queued jobs whose dispatch was lost (e.g. broker restart) are re-dispatched.
        stale_queued = db.execute(select(ChangeJob.id).where(ChangeJob.status == "queued")).scalars().all()
        # Jobs left "running" by a crashed worker for over an hour are failed explicitly, never silently retried.
        for job in db.execute(select(ChangeJob).where(ChangeJob.status == "running",
                                                      ChangeJob.started_at < now - timedelta(hours=1))).scalars():
            job.status = "failed"
            job.error = "Worker stopped while the job was running; verify the switch state before retrying"
            job.finished_at = now
            for r in job.results:
                if r.status in ("pending", "running"):
                    r.status = "failed" if r.status == "running" else "skipped"
                    r.message = job.error
        backup_due = _daily_backup_due(db)
    for cat in dispatched:
        poll_category.delay(cat)
    for jid in stale_queued:
        execute_job.delay(jid)
    if backup_due:
        scheduled_backups.delay()
    return {"dispatched": dispatched, "requeued_jobs": len(stale_queued), "backups": backup_due}


def _daily_backup_due(db) -> bool:  # type: ignore[no-untyped-def]
    if not sysset.get(db, "backups.enabled"):
        return False
    now = utcnow()
    if now.hour != int(sysset.get(db, "backups.schedule_hour")):
        return False
    marker = db.get(SystemSetting, "_state.last_scheduled_backup")
    today = now.date().isoformat()
    if marker and marker.value.get("v") == today:
        return False
    if marker is None:
        db.add(SystemSetting(key="_state.last_scheduled_backup", category="internal", value={"v": today}))
    else:
        marker.value = {"v": today}
    return True


@celery.task(name="app.workers.tasks.scheduled_backups")
def scheduled_backups() -> dict:
    from app.db.session import session_factory
    from app.services.devices import driver_for

    with db_session() as db:
        ids = list(db.execute(select(Switch.id).where(Switch.monitoring_enabled.is_(True))).scalars())
    ok = failed = 0
    for sid in ids:
        db = session_factory()()
        try:
            sw = db.get(Switch, sid)
            with driver_for(db, sw, "monitor") as drv:
                backups.take_backup(db, sw, drv, trigger="scheduled", dedupe=True)
            db.commit()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed += 1
            log.warning("scheduled backup failed for switch %s: %s", sid, exc)
            alerts.event(db, type="backup.failed", severity="warning", switch_id=sid,
                         message=f"Scheduled backup failed: {getattr(exc, 'message', exc.__class__.__name__)}")
            db.commit()
        finally:
            db.close()
    return {"ok": ok, "failed": failed}


@celery.task(name="app.workers.tasks.send_notifications")
def send_notifications() -> dict:
    with db_session() as db:
        return alerts.send_pending_notifications(db)


@celery.task(name="app.workers.tasks.maintenance")
def maintenance() -> dict:
    """Retention for non-hypertable data and expired sessions. Hypertables use TimescaleDB retention policies;
    if TimescaleDB is absent, metrics are trimmed here instead."""
    out = {}
    with db_session() as db:
        now = utcnow()
        out["sessions"] = db.execute(text("DELETE FROM sessions WHERE expires_at < :t OR revoked_at < :t2"),
                                     {"t": now - timedelta(days=1), "t2": now - timedelta(days=7)}).rowcount
        out["login_attempts"] = db.execute(text("DELETE FROM login_attempts WHERE ts < :t"),
                                           {"t": now - timedelta(days=90)}).rowcount
        out["events"] = db.execute(text("DELETE FROM switch_events WHERE ts < :t"),
                                   {"t": now - timedelta(days=365)}).rowcount
        out["mac"] = db.execute(text("DELETE FROM mac_learned_entries WHERE active = false AND last_seen < :t"),
                                {"t": now - timedelta(days=180)}).rowcount
        has_ts = db.execute(text("SELECT count(*) FROM pg_extension WHERE extname='timescaledb'")).scalar()
        if not has_ts:
            for table, days in (("switch_metrics", 90), ("port_metrics", 30), ("poe_metrics", 30)):
                out[table] = db.execute(text(f"DELETE FROM {table} WHERE ts < :t"),  # noqa: S608 - fixed names
                                        {"t": now - timedelta(days=days)}).rowcount
        keep_days = int(sysset.get(db, "audit.retention_days"))
        db.execute(text("SET LOCAL anm.audit_retention = 'on'"))
        out["audit"] = db.execute(text("DELETE FROM audit_logs WHERE ts < :t"),
                                  {"t": now - timedelta(days=keep_days)}).rowcount
        out["backups"] = backups.apply_retention(db)
    return out


@celery.task(name="app.workers.tasks.sync_integration")
def sync_integration(kind: str) -> dict:
    from app.integrations import service

    with db_session() as db:
        return service.sync(db, kind)
