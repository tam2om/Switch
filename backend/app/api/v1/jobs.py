"""Configuration change jobs (single-switch and bulk), approvals, templates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require, require_any
from app.core.errors import bad_request, conflict, not_found
from app.core.permissions import P, has_permission
from app.db.session import get_db
from app.models import ChangeJob, ChangeJobResult, ConfigurationTemplate, Switch, SwitchGroupMember, User
from app.services import audit
from app.services.jobs import engine
from app.services.jobs.operations import BULK_OPERATIONS, REGISTRY

router = APIRouter(tags=["jobs"])


class JobIn(BaseModel):
    operation: str
    params: dict = Field(default_factory=dict)
    switch_ids: list[int] = Field(default_factory=list)
    group_id: int | None = None
    batch_size: int | None = Field(default=None, ge=1, le=20)
    canary: bool = True
    max_failures: int = Field(default=1, ge=0, le=50)
    max_retries: int = Field(default=1, ge=0, le=3)
    acknowledge_risk: bool = False


class DecisionIn(BaseModel):
    comment: str = Field(default="", max_length=1000)


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=255)
    operation: str
    params: dict = Field(default_factory=dict)


def _targets(db: Session, body: JobIn) -> list[int]:
    ids = list(body.switch_ids)
    if body.group_id:
        ids += list(db.execute(select(SwitchGroupMember.switch_id).where(SwitchGroupMember.group_id == body.group_id)).scalars())
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise bad_request("Select at least one switch or group")
    return ids


def job_out(j: ChangeJob, with_results: bool = True, names: dict[int, str] | None = None) -> dict:
    d = {"id": j.id, "operation": j.operation, "title": j.title, "params": engine.public_params(j.params),
         "risk": j.risk, "risk_reasons": j.risk_reasons, "status": j.status, "requires_approval": j.requires_approval,
         "requested_by": j.requested_by_name, "requested_by_id": j.requested_by_id, "created_at": j.created_at,
         "started_at": j.started_at, "finished_at": j.finished_at, "batch_size": j.batch_size, "canary": j.canary,
         "max_failures": j.max_failures, "cancel_requested": j.cancel_requested, "summary": j.summary,
         "error": j.error, "target_count": len(j.results),
         "progress": {s: sum(1 for r in j.results if r.status == s) for s in
                      ("pending", "running", "success", "failed", "verify_failed", "skipped", "cancelled")},
         "approvals": [{"approver": a.approver_name, "decision": a.decision, "comment": a.comment,
                        "created_at": a.created_at} for a in j.approvals]}
    if with_results:
        d["results"] = [{"id": r.id, "switch_id": r.switch_id, "hostname": (names or {}).get(r.switch_id),
                         "batch_index": r.batch_index, "status": r.status, "attempts": r.attempts,
                         "pre_backup_id": r.pre_backup_id, "started_at": r.started_at, "finished_at": r.finished_at,
                         "message": r.message, "details": r.details} for r in j.results]
    return d


@router.get("/operations")
def operations(user: User = Depends(require(P.SWITCH_VIEW))) -> list[dict]:
    return [{"name": op.name, "title": op.title, "permission": op.permission.value,
             "allowed": has_permission(user.role, op.permission), "bulk": op.name in BULK_OPERATIONS,
             "warning": op.warning, "schema": op.Params.model_json_schema()} for op in REGISTRY.values()]


@router.post("/jobs/preview")
def preview(body: JobIn, user: User = Depends(require(P.JOB_VIEW)), db: Session = Depends(get_db)) -> dict:
    return engine.preview(db, user, body.operation, body.params, _targets(db, body))


@router.post("/jobs", status_code=201)
def create(body: JobIn, user: User = Depends(require(P.JOB_VIEW)), db: Session = Depends(get_db)) -> dict:
    job = engine.create_job(db, user, body.operation, body.params, _targets(db, body), batch_size=body.batch_size,
                            canary=body.canary, max_failures=body.max_failures, acknowledge_risk=body.acknowledge_risk,
                            max_retries=body.max_retries)
    db.commit()
    if job.status == "queued":
        engine.dispatch(job.id)
    db.refresh(job)
    return job_out(job)


@router.get("/jobs")
def list_jobs(status: str | None = None, switch_id: int | None = None, page: int = Query(1, ge=1),
              page_size: int = Query(50, le=200), user: User = Depends(require_any(P.JOB_VIEW, P.CHANGE_APPROVE)),
              db: Session = Depends(get_db)) -> dict:
    stmt = select(ChangeJob)
    if status:
        stmt = stmt.where(ChangeJob.status.in_(status.split(",")))
    if switch_id:
        stmt = stmt.where(ChangeJob.id.in_(select(ChangeJobResult.job_id).where(ChangeJobResult.switch_id == switch_id)))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(ChangeJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"items": [job_out(j, with_results=False) for j in rows], "total": total, "page": page}


def _job(db: Session, job_id: int) -> ChangeJob:
    j = db.get(ChangeJob, job_id)
    if j is None:
        raise not_found("Job")
    return j


@router.get("/jobs/{job_id}")
def get_job(job_id: int, user: User = Depends(require_any(P.JOB_VIEW, P.CHANGE_APPROVE)),
            db: Session = Depends(get_db)) -> dict:
    j = _job(db, job_id)
    names = dict(db.execute(select(Switch.id, Switch.hostname).where(
        Switch.id.in_([r.switch_id for r in j.results]))).all())
    return job_out(j, names=names)


@router.post("/jobs/{job_id}/approve")
def approve(job_id: int, body: DecisionIn, user: User = Depends(require(P.CHANGE_APPROVE)),
            db: Session = Depends(get_db)) -> dict:
    j = engine.approve(db, _job(db, job_id), user, body.comment)
    db.commit()
    engine.dispatch(j.id)
    db.refresh(j)
    return job_out(j)


@router.post("/jobs/{job_id}/reject")
def reject(job_id: int, body: DecisionIn, user: User = Depends(require(P.CHANGE_APPROVE)),
           db: Session = Depends(get_db)) -> dict:
    j = engine.reject(db, _job(db, job_id), user, body.comment)
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, user: User = Depends(require(P.JOB_VIEW)), db: Session = Depends(get_db)) -> dict:
    j = engine.cancel(db, _job(db, job_id), user)
    db.commit()
    return job_out(j)


@router.post("/jobs/{job_id}/retry", status_code=201)
def retry(job_id: int, user: User = Depends(require(P.JOB_VIEW)), db: Session = Depends(get_db)) -> dict:
    j = _job(db, job_id)
    if j.status not in engine.TERMINAL:
        raise conflict("Job is still active")
    new = engine.retry_failed(db, j, user)
    db.commit()
    if new.status == "queued":
        engine.dispatch(new.id)
    db.refresh(new)
    return job_out(new)


# ------------------------------------------------------------------ templates

def _tpl_out(t: ConfigurationTemplate) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "operation": t.operation,
            "params": engine.public_params(t.params), "created_at": t.created_at, "updated_at": t.updated_at}


@router.get("/templates")
def list_templates(user: User = Depends(require(P.JOB_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    return [_tpl_out(t) for t in db.execute(select(ConfigurationTemplate).order_by(ConfigurationTemplate.name)).scalars()]


@router.post("/templates", status_code=201)
def create_template(body: TemplateIn, user: User = Depends(require(P.TEMPLATE_MANAGE)), db: Session = Depends(get_db)) -> dict:
    op = REGISTRY.get(body.operation)
    if op is None or body.operation in ("config_restore",):
        raise bad_request("This operation cannot be templated")
    p = op.parse(body.params)
    if db.execute(select(ConfigurationTemplate).where(ConfigurationTemplate.name == body.name)).first():
        raise conflict("Template name already exists")
    t = ConfigurationTemplate(name=body.name, description=body.description, operation=body.operation,
                              params=engine._seal_params(p.model_dump()), created_by_id=user.id)
    db.add(t)
    db.flush()
    audit.record(db, action="template.create", actor=user, target_type="template", target_id=t.id,
                 details={"name": t.name, "operation": t.operation})
    db.commit()
    return _tpl_out(t)


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplateIn, user: User = Depends(require(P.TEMPLATE_MANAGE)),
                    db: Session = Depends(get_db)) -> dict:
    t = db.get(ConfigurationTemplate, template_id)
    if t is None:
        raise not_found("Template")
    op = REGISTRY.get(body.operation)
    if op is None or body.operation == "config_restore":
        raise bad_request("This operation cannot be templated")
    t.name, t.description, t.operation = body.name, body.description, body.operation
    t.params = engine._seal_params(op.parse(body.params).model_dump())
    audit.record(db, action="template.update", actor=user, target_type="template", target_id=t.id)
    db.commit()
    return _tpl_out(t)


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, user: User = Depends(require(P.TEMPLATE_MANAGE)), db: Session = Depends(get_db)) -> dict:
    t = db.get(ConfigurationTemplate, template_id)
    if t is None:
        raise not_found("Template")
    audit.record(db, action="template.delete", actor=user, target_type="template", target_id=t.id, details={"name": t.name})
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.post("/templates/{template_id}/apply", status_code=201)
def apply_template(template_id: int, body: JobIn, user: User = Depends(require(P.JOB_VIEW)),
                   db: Session = Depends(get_db)) -> dict:
    t = db.get(ConfigurationTemplate, template_id)
    if t is None:
        raise not_found("Template")
    params = engine._unseal_params(t.params)
    params.update(body.params or {})
    job = engine.create_job(db, user, t.operation, params, _targets(db, body), batch_size=body.batch_size,
                            canary=body.canary, max_failures=body.max_failures, acknowledge_risk=body.acknowledge_risk)
    db.commit()
    if job.status == "queued":
        engine.dispatch(job.id)
    db.refresh(job)
    return job_out(job)
