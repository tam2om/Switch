"""Configuration change engine.

Pipeline for every change (per target switch):
  1 authenticate user (API layer)       2 verify role/permission       3 validate request
  4 read current state (pre-check)      5 identify risk                6 pre-change backup
  7 approval when required              8 execute                      9 verify by reading the device back
 10 record result                      11 audit record

Bulk execution uses a canary (first switch alone), then controlled batches. Execution stops when failures exceed
max_failures. High/critical risk jobs run one switch at a time. Jobs never run automatically without the
approval policy being satisfied, and critical-risk jobs require an explicit risk acknowledgement.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import get_keyring
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.permissions import P, has_permission
from app.db.base import utcnow
from app.db.session import session_factory
from app.drivers.base import DriverError
from app.models import ChangeApproval, ChangeJob, ChangeJobResult, Switch, User
from app.services import alerts, audit, backups, polling
from app.services import settings as sysset
from app.services.devices import driver_for
from app.services.jobs.operations import (
    BULK_OPERATIONS,
    REGISTRY,
    RISK_ORDER,
    SECRET_PARAMS,
    PrecheckFailed,
    max_risk,
)

log = logging.getLogger(__name__)
TERMINAL = {"completed", "partial", "failed", "cancelled", "rejected"}


# ------------------------------------------------------------------ secrets in parameters

def _seal_params(params: dict) -> dict:
    secret = {k: v for k, v in params.items() if k in SECRET_PARAMS and v}
    if not secret:
        return params
    import json

    sealed = {k: ("********" if k in secret else v) for k, v in params.items()}
    sealed["_sealed"] = get_keyring().encrypt_str(json.dumps(secret), "job-params")
    return sealed


def _unseal_params(params: dict) -> dict:
    if "_sealed" not in params:
        return params
    import json

    secret = json.loads(get_keyring().decrypt_str(params["_sealed"], "job-params"))
    out = {k: v for k, v in params.items() if k != "_sealed"}
    out.update(secret)
    return out


def public_params(params: dict) -> dict:
    return {k: v for k, v in params.items() if k != "_sealed"}


# ------------------------------------------------------------------ creation / approval

def preview(db: Session, user: User, operation: str, params: dict, switch_ids: list[int]) -> dict:
    op = REGISTRY.get(operation)
    if op is None:
        raise bad_request(f"Unknown operation '{operation}'", "unknown_operation")
    if not has_permission(user.role, op.permission):
        raise forbidden()
    p = op.parse(params)
    switches = _load_switches(db, switch_ids)
    per_switch = []
    overall = "low"
    reasons: list[str] = []
    for sw in switches:
        r = op.assess(db, sw, p)
        overall = max_risk(overall, r.level)
        per_switch.append({"switch_id": sw.id, "hostname": sw.hostname, "risk": r.level, "reasons": r.reasons,
                           "simulated": sw.is_simulated})
        for reason in r.reasons:
            tagged = f"{sw.hostname}: {reason}" if len(switches) > 1 else reason
            if tagged not in reasons:
                reasons.append(tagged)
    if len(switches) >= 10:
        overall = max_risk(overall, "medium")
        reasons.append(f"Fleet change across {len(switches)} switches")
    threshold = sysset.get(db, "changes.require_approval_risk")
    requires_approval = RISK_ORDER.index(overall) >= RISK_ORDER.index(threshold)
    return {"operation": operation, "title": op.describe(p), "risk": overall, "reasons": reasons,
            "requires_approval": requires_approval, "requires_acknowledgement": overall == "critical",
            "warning": op.warning, "takes_backup": op.takes_backup, "switches": per_switch}


def _load_switches(db: Session, switch_ids: list[int]) -> list[Switch]:
    ids = list(dict.fromkeys(int(i) for i in switch_ids))
    if not ids:
        raise bad_request("Select at least one switch")
    if len(ids) > 200:
        raise bad_request("A single job may target at most 200 switches")
    rows = db.execute(select(Switch).where(Switch.id.in_(ids))).unique().scalars().all()
    if len(rows) != len(ids):
        raise not_found("Switch")
    by_id = {s.id: s for s in rows}
    return [by_id[i] for i in ids]


def create_job(db: Session, user: User, operation: str, params: dict, switch_ids: list[int], *,
               batch_size: int | None = None, canary: bool = True, max_failures: int = 1,
               acknowledge_risk: bool = False, max_retries: int = 1) -> ChangeJob:
    op = REGISTRY.get(operation)
    if op is None:
        raise bad_request(f"Unknown operation '{operation}'", "unknown_operation")
    if not has_permission(user.role, op.permission):
        raise forbidden()
    if len(switch_ids) > 1:
        if not has_permission(user.role, P.BULK_EXECUTE):
            raise forbidden("Bulk operations require the bulk.execute permission")
        if operation not in BULK_OPERATIONS:
            raise bad_request(f"'{operation}' cannot be executed on multiple switches at once")
    pv = preview(db, user, operation, params, switch_ids)
    if pv["requires_acknowledgement"] and not acknowledge_risk:
        raise bad_request("This change is critical risk. Review the warnings and acknowledge the risk to continue.",
                          "risk_acknowledgement_required", {"preview": pv})
    p = op.parse(params)
    batch = batch_size or int(sysset.get(db, "jobs.default_batch_size"))
    if pv["risk"] in ("high", "critical"):
        batch = 1  # high-impact changes never run in parallel
    job = ChangeJob(operation=operation, title=pv["title"], params=_seal_params(p.model_dump()), risk=pv["risk"],
                    risk_reasons=pv["reasons"], requires_approval=pv["requires_approval"],
                    status="pending_approval" if pv["requires_approval"] else "queued",
                    requested_by_id=user.id, requested_by_name=user.username, batch_size=max(1, min(batch, 20)),
                    canary=canary, max_failures=max(0, max_failures), max_retries=max(0, min(max_retries, 3)),
                    acknowledged_risk=acknowledge_risk)
    db.add(job)
    db.flush()
    for idx, sw in enumerate(_load_switches(db, switch_ids)):
        db.add(ChangeJobResult(job_id=job.id, switch_id=sw.id, status="pending", batch_index=idx))
    audit.record(db, action="job.create", category="operational", actor=user, target_type="job", target_id=job.id,
                 switch_id=switch_ids[0] if len(switch_ids) == 1 else None,
                 details={"operation": operation, "risk": job.risk, "switches": list(switch_ids),
                          "params": public_params(job.params), "requires_approval": job.requires_approval})
    db.flush()
    return job


def approve(db: Session, job: ChangeJob, user: User, comment: str = "") -> ChangeJob:
    if not has_permission(user.role, P.CHANGE_APPROVE):
        raise forbidden("Only users with change approval permission can approve")
    if job.status != "pending_approval":
        raise conflict(f"Job is {job.status}, not pending approval")
    if job.requested_by_id == user.id and not sysset.get(db, "changes.allow_self_approval"):
        raise forbidden("A different user must approve this change (four-eyes principle)")
    db.add(ChangeApproval(job_id=job.id, approver_id=user.id, approver_name=user.username, decision="approved",
                          comment=comment[:1000]))
    job.status = "queued"
    audit.record(db, action="job.approve", category="operational", actor=user, target_type="job", target_id=job.id,
                 details={"comment": comment})
    return job


def reject(db: Session, job: ChangeJob, user: User, comment: str = "") -> ChangeJob:
    if not has_permission(user.role, P.CHANGE_APPROVE):
        raise forbidden()
    if job.status != "pending_approval":
        raise conflict(f"Job is {job.status}, not pending approval")
    db.add(ChangeApproval(job_id=job.id, approver_id=user.id, approver_name=user.username, decision="rejected",
                          comment=comment[:1000]))
    job.status = "rejected"
    job.finished_at = utcnow()
    for r in job.results:
        r.status = "cancelled"
    audit.record(db, action="job.reject", category="operational", actor=user, target_type="job", target_id=job.id,
                 details={"comment": comment})
    return job


def cancel(db: Session, job: ChangeJob, user: User) -> ChangeJob:
    if job.status in TERMINAL:
        raise conflict(f"Job is already {job.status}")
    if job.requested_by_id != user.id and not has_permission(user.role, P.CHANGE_APPROVE):
        raise forbidden("Only the requester or an approver can cancel this job")
    if job.status in ("pending_approval", "queued"):
        job.status = "cancelled"
        job.finished_at = utcnow()
        for r in job.results:
            if r.status == "pending":
                r.status = "cancelled"
    else:
        # Running: stop before the next switch. A switch already being changed finishes and is verified.
        job.cancel_requested = True
    audit.record(db, action="job.cancel", category="operational", actor=user, target_type="job", target_id=job.id)
    return job


def retry_failed(db: Session, job: ChangeJob, user: User) -> ChangeJob:
    """Create a new job targeting only the switches that failed."""
    failed = [r.switch_id for r in job.results if r.status in ("failed", "verify_failed", "skipped")]
    if not failed:
        raise conflict("No failed switches to retry")
    return create_job(db, user, job.operation, _unseal_params(job.params), failed, batch_size=job.batch_size,
                      canary=False, max_failures=job.max_failures, acknowledge_risk=job.acknowledged_risk)


# ------------------------------------------------------------------ execution

def _batches(results: list[ChangeJobResult], canary: bool, size: int) -> list[list[int]]:
    ids = [r.id for r in sorted(results, key=lambda r: r.batch_index)]
    out: list[list[int]] = []
    if canary and len(ids) > 1:
        out.append(ids[:1])
        ids = ids[1:]
    for i in range(0, len(ids), size):
        out.append(ids[i:i + size])
    return out


def run_job(job_id: int) -> dict:
    factory = session_factory()
    with factory() as db:
        job = db.get(ChangeJob, job_id)
        if job is None:
            return {"error": "not found"}
        if job.status != "queued":
            return {"skipped": f"job is {job.status}"}
        job.status = "running"
        job.started_at = utcnow()
        db.commit()
        batches = _batches(job.results, job.canary, job.batch_size)
        parallel = job.risk not in ("high", "critical")
    failures = 0
    stopped_reason = ""
    for bi, batch in enumerate(batches):
        with factory() as db:
            job = db.get(ChangeJob, job_id)
            assert job is not None
            if job.cancel_requested:
                stopped_reason = "cancelled by user"
                break
            max_f = job.max_failures
        if parallel and len(batch) > 1:
            with ThreadPoolExecutor(max_workers=len(batch)) as pool:
                outcomes = list(pool.map(_run_target, batch))
        else:
            outcomes = [_run_target(rid) for rid in batch]
        failures += sum(1 for o in outcomes if o not in ("success",))
        if bi == 0 and len(batches) > 1 and failures and job.canary:
            stopped_reason = "canary switch failed; remaining switches were not changed"
            break
        if failures > max_f:
            stopped_reason = f"stopped after {failures} failure(s) (limit {max_f})"
            break
    with factory() as db:
        job = db.get(ChangeJob, job_id)
        assert job is not None
        counts: dict[str, int] = {}
        for r in job.results:
            if r.status == "pending":
                r.status = "cancelled" if job.cancel_requested else "skipped"
                r.message = stopped_reason or r.message
            counts[r.status] = counts.get(r.status, 0) + 1
        ok = counts.get("success", 0)
        total = len(job.results)
        if job.cancel_requested and ok < total:
            job.status = "cancelled"
        elif ok == total:
            job.status = "completed"
        elif ok == 0:
            job.status = "failed"
        else:
            job.status = "partial"
        job.summary = {"counts": counts, "stopped_reason": stopped_reason}
        job.error = stopped_reason
        job.finished_at = utcnow()
        audit.record(db, action="job.finish", category="operational", actor_name=job.requested_by_name,
                     target_type="job", target_id=job.id, result="success" if job.status == "completed" else "failure",
                     details={"status": job.status, "counts": counts, "stopped_reason": stopped_reason})
        db.commit()
        return {"job_id": job_id, "status": job.status, "counts": counts}


CHANGE_LOCK_WAIT_SECONDS = 900


def _switch_change_lock(switch_id: int) -> Any:
    """Only one change may touch a switch at a time, across jobs and workers. Waits for a running change on the
    same switch to finish; fails closed (returns None) if the lock cannot be obtained."""
    import redis

    r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=5)
    lock = r.lock(f"anm:change:{switch_id}", timeout=3600, blocking_timeout=CHANGE_LOCK_WAIT_SECONDS)
    try:
        return lock if lock.acquire() else None
    except redis.RedisError:
        return None


def _run_target(result_id: int) -> str:
    factory = session_factory()
    with factory() as db:
        r = db.get(ChangeJobResult, result_id)
        assert r is not None
        switch_id = r.switch_id
    lock = _switch_change_lock(switch_id)
    if lock is None:
        with factory() as db:
            r = db.get(ChangeJobResult, result_id)
            assert r is not None
            r.status = "failed"
            r.message = "Another change is still running on this switch (or the lock service is unavailable); nothing was changed"
            r.finished_at = utcnow()
            db.commit()
        return "failed"
    try:
        return _run_target_locked(result_id)
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - lock may have expired; nothing else to do
            log.warning("change lock for switch %s already released", switch_id)


def _run_target_locked(result_id: int) -> str:
    factory = session_factory()
    db = factory()
    try:
        r = db.get(ChangeJobResult, result_id)
        assert r is not None
        job = r.job
        sw = db.get(Switch, r.switch_id)
        op = REGISTRY[job.operation]
        params = op.parse(_unseal_params(job.params))
        requester = db.get(User, job.requested_by_id) if job.requested_by_id else None
        r.status = "running"
        r.started_at = utcnow()
        db.commit()
        details: dict[str, Any] = {"steps": []}
        attempts = 0
        while True:
            attempts += 1
            try:
                with driver_for(db, sw, "config") as drv:
                    details["steps"].append({"step": "connect", "ok": True, "simulated": drv.is_simulated})
                    op.precheck(db, sw, drv, params)
                    details["steps"].append({"step": "precheck", "ok": True})
                    if job.operation == "config_backup":
                        b = backups.take_backup(db, sw, drv, trigger="manual", user=requester, job_id=job.id,
                                                note=getattr(params, "note", ""))
                        r.pre_backup_id = b.id
                        details["steps"].append({"step": "backup", "ok": b.verify_status == "verified",
                                                 "backup_id": b.id})
                        ok, vdetails = b.verify_status == "verified", {"backup_id": b.id}
                    else:
                        if op.takes_backup:
                            b = backups.take_backup(db, sw, drv, trigger="pre_change", user=requester, job_id=job.id,
                                                    note=f"before job #{job.id}")
                            r.pre_backup_id = b.id
                            details["steps"].append({"step": "pre_backup", "ok": b.verify_status == "verified",
                                                     "backup_id": b.id})
                            if b.verify_status != "verified":
                                raise PrecheckFailed("Pre-change backup could not be verified; change not applied")
                            db.commit()
                        results = op.execute(db, sw, drv, params)
                        details["steps"].append({"step": "execute", "ok": all(x.ok for x in results),
                                                 "protocols": sorted({x.protocol for x in results}),
                                                 "messages": [x.message for x in results][:20]})
                        ok, vdetails = op.verify(db, sw, drv, params)
                        details["steps"].append({"step": "verify", "ok": ok, **vdetails})
                        if ok and op.saves_config:
                            drv.write_memory()
                            details["steps"].append({"step": "write_memory", "ok": True})
                    if ok and op.refresh:
                        try:
                            polling.CATEGORIES[op.refresh](db, sw, drv)
                        except DriverError as exc:
                            details["steps"].append({"step": "refresh", "ok": False, "error": exc.message})
                r.status = "success" if ok else "verify_failed"
                r.message = "Applied and verified" if ok else "Change applied but verification did not match"
                break
            except PrecheckFailed as exc:
                db.rollback()
                r = db.get(ChangeJobResult, result_id)
                r.status = "failed"
                r.message = f"Pre-check failed: {exc}"
                details["steps"].append({"step": "precheck", "ok": False, "error": str(exc)})
                break
            except DriverError as exc:
                db.rollback()
                r = db.get(ChangeJobResult, result_id)
                sw = db.get(Switch, r.switch_id)
                details["steps"].append({"step": "error", "ok": False, "attempt": attempts, **exc.to_dict()})
                if exc.retriable and attempts <= job.max_retries:
                    time.sleep(min(2 * attempts, 5))
                    continue
                r.status = "failed"
                r.message = exc.message
                break
        r.attempts = attempts
        r.finished_at = utcnow()
        r.details = details
        if r.status != "success":
            alerts.raise_alert(db, type="config_operation_failed", switch=sw,
                               message=f"Job #{job.id} ({job.title}) {r.status} on {sw.hostname}: {r.message}"[:500],
                               dedup_suffix=str(job.id), details={"job_id": job.id})
        alerts.event(db, type=f"change.{r.status}", switch_id=sw.id,
                     severity="info" if r.status == "success" else "major",
                     message=f"Job #{job.id} {job.title}: {r.message}"[:1000], details={"job_id": job.id})
        audit.record(db, action=f"change.{job.operation}", category="operational", actor_name=job.requested_by_name,
                     result="success" if r.status == "success" else "failure", target_type="switch",
                     target_id=sw.id, switch_id=sw.id,
                     details={"job_id": job.id, "status": r.status, "message": r.message,
                              "params": public_params(job.params), "pre_backup_id": r.pre_backup_id,
                              "simulated": sw.is_simulated})
        db.commit()
        return r.status
    except Exception as exc:  # noqa: BLE001 - never leave a target "running"
        log.exception("job target %s crashed", result_id)
        db.rollback()
        r = db.get(ChangeJobResult, result_id)
        if r is not None:
            r.status = "failed"
            r.message = f"Internal error: {exc.__class__.__name__}"
            r.finished_at = utcnow()
            db.commit()
        return "failed"
    finally:
        db.close()


def dispatch(job_id: int) -> None:
    """Queue job execution on a Celery worker (or run inline when eager)."""
    from app.workers.tasks import execute_job

    execute_job.delay(job_id)
