"""Sites, switch groups and switch models."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import conflict, not_found
from app.core.permissions import P
from app.db.session import get_db
from app.models import (
    ChangeJob,
    ChangeJobResult,
    Site,
    Switch,
    SwitchGroup,
    SwitchGroupMember,
    SwitchModel,
    User,
)
from app.services import audit

router = APIRouter(tags=["inventory"])


class SiteIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    address: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=255)


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=255)
    switch_ids: list[int] | None = None


@router.get("/sites")
def list_sites(user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    counts = dict(db.execute(select(Switch.site_id, func.count()).group_by(Switch.site_id)).all())
    return [{"id": s.id, "name": s.name, "address": s.address, "description": s.description,
             "switch_count": counts.get(s.id, 0)} for s in db.execute(select(Site).order_by(Site.name)).scalars()]


@router.post("/sites", status_code=201)
def create_site(body: SiteIn, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    if db.execute(select(Site).where(Site.name == body.name)).first():
        raise conflict("Site name already exists")
    s = Site(**body.model_dump())
    db.add(s)
    db.flush()
    audit.record(db, action="site.create", actor=user, target_type="site", target_id=s.id, details=body.model_dump())
    db.commit()
    return {"id": s.id, **body.model_dump()}


@router.patch("/sites/{site_id}")
def update_site(site_id: int, body: SiteIn, user: User = Depends(require(P.SWITCH_MANAGE)),
                db: Session = Depends(get_db)) -> dict:
    s = db.get(Site, site_id)
    if s is None:
        raise not_found("Site")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    audit.record(db, action="site.update", actor=user, target_type="site", target_id=s.id, details=body.model_dump())
    db.commit()
    return {"id": s.id, **body.model_dump()}


@router.delete("/sites/{site_id}")
def delete_site(site_id: int, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    s = db.get(Site, site_id)
    if s is None:
        raise not_found("Site")
    audit.record(db, action="site.delete", actor=user, target_type="site", target_id=s.id, details={"name": s.name})
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.get("/groups")
def list_groups(user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    members: dict[int, list[int]] = {}
    for gid, sid in db.execute(select(SwitchGroupMember.group_id, SwitchGroupMember.switch_id)).all():
        members.setdefault(gid, []).append(sid)
    return [{"id": g.id, "name": g.name, "description": g.description, "switch_ids": members.get(g.id, [])}
            for g in db.execute(select(SwitchGroup).order_by(SwitchGroup.name)).scalars()]


@router.post("/groups", status_code=201)
def create_group(body: GroupIn, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    if db.execute(select(SwitchGroup).where(SwitchGroup.name == body.name)).first():
        raise conflict("Group name already exists")
    g = SwitchGroup(name=body.name, description=body.description)
    db.add(g)
    db.flush()
    for sid in set(body.switch_ids or []):
        if db.get(Switch, sid) is None:
            raise not_found("Switch")
        db.add(SwitchGroupMember(group_id=g.id, switch_id=sid))
    audit.record(db, action="group.create", actor=user, target_type="group", target_id=g.id, details=body.model_dump())
    db.commit()
    return {"id": g.id, "name": g.name, "description": g.description, "switch_ids": body.switch_ids or []}


@router.patch("/groups/{group_id}")
def update_group(group_id: int, body: GroupIn, user: User = Depends(require(P.SWITCH_MANAGE)),
                 db: Session = Depends(get_db)) -> dict:
    g = db.get(SwitchGroup, group_id)
    if g is None:
        raise not_found("Group")
    g.name, g.description = body.name, body.description
    if body.switch_ids is not None:
        db.query(SwitchGroupMember).filter(SwitchGroupMember.group_id == g.id).delete()
        for sid in set(body.switch_ids):
            if db.get(Switch, sid) is None:
                raise not_found("Switch")
            db.add(SwitchGroupMember(group_id=g.id, switch_id=sid))
    audit.record(db, action="group.update", actor=user, target_type="group", target_id=g.id, details=body.model_dump())
    db.commit()
    return {"id": g.id, "name": g.name, "description": g.description, "switch_ids": body.switch_ids}


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    g = db.get(SwitchGroup, group_id)
    if g is None:
        raise not_found("Group")
    audit.record(db, action="group.delete", actor=user, target_type="group", target_id=g.id, details={"name": g.name})
    db.delete(g)
    db.commit()
    return {"ok": True}


@router.get("/models")
def list_models(user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    # Change operations count as verified on a model when a job on a physical switch of that model applied the
    # change and read it back successfully.
    verified_ops: dict[str, set[str]] = {}
    for pn, op in db.execute(
            select(Switch.product_number, ChangeJob.operation)
            .join(ChangeJobResult, ChangeJobResult.job_id == ChangeJob.id)
            .join(Switch, Switch.id == ChangeJobResult.switch_id)
            .where(ChangeJobResult.status == "success", Switch.is_simulated.is_(False)).distinct()).all():
        if pn:
            verified_ops.setdefault(pn, set()).add(op)
    return [{"id": m.id, "product_number": m.product_number, "name": m.name, "family": m.family,
             "access_ports": m.access_ports, "uplink_ports": m.uplink_ports, "poe_budget_w": m.poe_budget_w,
             "hardware_verified": m.hardware_verified, "port_layout": m.port_layout,
             "hardware_evidence": m.hardware_evidence or {},
             "verified_operations": sorted(verified_ops.get(m.product_number, set()))}
            for m in db.execute(select(SwitchModel).order_by(SwitchModel.product_number)).scalars()]
