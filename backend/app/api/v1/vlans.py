"""Fleet VLAN catalogue, cross-switch matrix, consistency report and comparison."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import conflict, not_found
from app.core.permissions import P
from app.db.session import get_db
from app.drivers.aruba.aos_switch import cli_commands as cli
from app.models import Switch, SwitchPort, SwitchVlan, User, Vlan
from app.services import audit

router = APIRouter(prefix="/vlans", tags=["vlans"])


class VlanIn(BaseModel):
    vlan_id: int = Field(ge=1, le=4094)
    name: str
    description: str = Field(default="", max_length=255)
    is_management: bool = False
    is_voice: bool = False

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return cli.vlan_name(v)


@router.get("")
def catalogue(user: User = Depends(require(P.VLAN_VIEW)), db: Session = Depends(get_db)) -> list[dict]:
    plan = {v.vlan_id: v for v in db.execute(select(Vlan)).scalars()}
    present: dict[int, dict] = {}
    for sv in db.execute(select(SwitchVlan)).scalars():
        d = present.setdefault(sv.vlan_id, {"switches": 0, "names": set()})
        d["switches"] += 1
        d["names"].add(sv.name)
    out = []
    for vid in sorted(set(plan) | set(present)):
        p = plan.get(vid)
        pres = present.get(vid, {"switches": 0, "names": set()})
        out.append({"vlan_id": vid, "name": p.name if p else sorted(pres["names"])[0] if pres["names"] else "",
                    "description": p.description if p else "", "in_catalogue": p is not None,
                    "is_management": p.is_management if p else False, "is_voice": p.is_voice if p else False,
                    "switch_count": pres["switches"], "names_on_switches": sorted(pres["names"]),
                    "name_mismatch": bool(p and pres["names"] and pres["names"] != {p.name})})
    return out


@router.post("", status_code=201)
def add_to_catalogue(body: VlanIn, user: User = Depends(require(P.VLAN_MANAGE)), db: Session = Depends(get_db)) -> dict:
    if db.execute(select(Vlan).where(Vlan.vlan_id == body.vlan_id)).first():
        raise conflict("VLAN already in the catalogue")
    db.add(Vlan(**body.model_dump()))
    audit.record(db, action="vlan_catalogue.create", actor=user, target_type="vlan", target_id=body.vlan_id,
                 details=body.model_dump())
    db.commit()
    return body.model_dump()


@router.put("/{vlan_id}")
def update_catalogue(vlan_id: int, body: VlanIn, user: User = Depends(require(P.VLAN_MANAGE)),
                     db: Session = Depends(get_db)) -> dict:
    v = db.execute(select(Vlan).where(Vlan.vlan_id == vlan_id)).scalar_one_or_none()
    if v is None:
        raise not_found("VLAN")
    for k, val in body.model_dump(exclude={"vlan_id"}).items():
        setattr(v, k, val)
    audit.record(db, action="vlan_catalogue.update", actor=user, target_type="vlan", target_id=vlan_id,
                 details=body.model_dump())
    db.commit()
    return body.model_dump()


@router.delete("/{vlan_id}")
def remove_from_catalogue(vlan_id: int, user: User = Depends(require(P.VLAN_MANAGE)),
                          db: Session = Depends(get_db)) -> dict:
    """Removes the VLAN from the plan only. Deleting it from switches is a separate (approved) change job."""
    v = db.execute(select(Vlan).where(Vlan.vlan_id == vlan_id)).scalar_one_or_none()
    if v is None:
        raise not_found("VLAN")
    db.delete(v)
    audit.record(db, action="vlan_catalogue.delete", actor=user, target_type="vlan", target_id=vlan_id)
    db.commit()
    return {"ok": True}


@router.get("/matrix")
def matrix(user: User = Depends(require(P.VLAN_VIEW)), db: Session = Depends(get_db)) -> dict:
    switches = db.execute(select(Switch).order_by(Switch.hostname)).unique().scalars().all()
    sv = db.execute(select(SwitchVlan)).scalars().all()
    ports = db.execute(select(SwitchPort.switch_id, SwitchPort.name, SwitchPort.untagged_vlan,
                              SwitchPort.tagged_vlans)).all()
    counts: dict[tuple[int, int], dict] = {}
    for sid, _name, un, tg in ports:
        if un:
            counts.setdefault((sid, un), {"u": 0, "t": 0})["u"] += 1
        for t in tg or []:
            counts.setdefault((sid, t), {"u": 0, "t": 0})["t"] += 1
    vids = sorted({v.vlan_id for v in sv} | {v.vlan_id for v in db.execute(select(Vlan)).scalars()})
    present = {(v.switch_id, v.vlan_id): v.name for v in sv}
    rows = []
    for s in switches:
        cells = {}
        for vid in vids:
            if (s.id, vid) in present:
                c = counts.get((s.id, vid), {"u": 0, "t": 0})
                cells[str(vid)] = {"name": present[(s.id, vid)], "untagged": c["u"], "tagged": c["t"]}
        rows.append({"switch_id": s.id, "hostname": s.hostname, "is_simulated": s.is_simulated,
                     "mgmt_vlan": s.mgmt_vlan, "cells": cells})
    return {"vlans": vids, "rows": rows}


@router.get("/consistency")
def consistency(user: User = Depends(require(P.VLAN_VIEW)), db: Session = Depends(get_db)) -> dict:
    plan = {v.vlan_id: v for v in db.execute(select(Vlan)).scalars()}
    switches = db.execute(select(Switch)).unique().scalars().all()
    sv: dict[int, dict[int, str]] = {}
    for v in db.execute(select(SwitchVlan)).scalars():
        sv.setdefault(v.switch_id, {})[v.vlan_id] = v.name
    issues = []
    for s in switches:
        have = sv.get(s.id, {})
        if not have:
            issues.append({"switch_id": s.id, "hostname": s.hostname, "type": "no_data",
                           "message": "No VLAN data collected yet"})
            continue
        for vid, p in plan.items():
            if vid not in have:
                issues.append({"switch_id": s.id, "hostname": s.hostname, "type": "missing", "vlan_id": vid,
                               "message": f"VLAN {vid} ({p.name}) from the plan is missing"})
            elif have[vid] != p.name:
                issues.append({"switch_id": s.id, "hostname": s.hostname, "type": "name_mismatch", "vlan_id": vid,
                               "message": f"VLAN {vid} is named '{have[vid]}' (plan: '{p.name}')"})
        for vid in have:
            if plan and vid not in plan and vid != 1:
                issues.append({"switch_id": s.id, "hostname": s.hostname, "type": "unplanned", "vlan_id": vid,
                               "message": f"VLAN {vid} ({have[vid]}) is not in the VLAN plan"})
        mgmt_plan = [v.vlan_id for v in plan.values() if v.is_management]
        if mgmt_plan and s.mgmt_vlan and s.mgmt_vlan not in mgmt_plan:
            issues.append({"switch_id": s.id, "hostname": s.hostname, "type": "mgmt_vlan",
                           "message": f"Management VLAN {s.mgmt_vlan} differs from the plan {mgmt_plan}"})
    return {"plan_size": len(plan), "switches": len(switches), "issues": issues,
            "consistent": not [i for i in issues if i["type"] != "no_data"]}


@router.get("/compare")
def compare(a: int = Query(...), b: int = Query(...), user: User = Depends(require(P.VLAN_VIEW)),
            db: Session = Depends(get_db)) -> dict:
    sa, sb = db.get(Switch, a), db.get(Switch, b)
    if sa is None or sb is None:
        raise not_found("Switch")
    va = {v.vlan_id: v.name for v in db.execute(select(SwitchVlan).where(SwitchVlan.switch_id == a)).scalars()}
    vb = {v.vlan_id: v.name for v in db.execute(select(SwitchVlan).where(SwitchVlan.switch_id == b)).scalars()}
    rows = []
    for vid in sorted(set(va) | set(vb)):
        rows.append({"vlan_id": vid, "a": va.get(vid), "b": vb.get(vid),
                     "status": "both" if vid in va and vid in vb and va[vid] == vb[vid] else
                     "name_differs" if vid in va and vid in vb else "only_a" if vid in va else "only_b"})
    return {"a": {"id": sa.id, "hostname": sa.hostname}, "b": {"id": sb.id, "hostname": sb.hostname}, "rows": rows}
