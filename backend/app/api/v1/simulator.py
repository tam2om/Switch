"""Simulator management (demo / test environments only). Disabled unless ANM_SIMULATOR_ENABLED=true."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, not_found
from app.core.permissions import P
from app.db.session import get_db
from app.models import Switch, User
from app.services import audit
from app.services import simulator as svc

router = APIRouter(prefix="/simulator", tags=["simulator"])


def _enabled() -> None:
    s = get_settings()
    if not s.simulator_enabled and s.environment != "test":
        raise AppError(404, "simulator_disabled", "Simulator mode is disabled on this installation")


class SeedIn(BaseModel):
    count: int = Field(ge=1, le=200)


class FaultIn(BaseModel):
    offline: bool | None = None
    poe_fault_port: str | None = None
    flapping_port: str | None = None
    clear: bool = False


@router.post("/seed")
def seed(body: SeedIn, user: User = Depends(require(P.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    _enabled()
    res = svc.seed(db, body.count)
    audit.record(db, action="simulator.seed", category="system", actor=user, details=res)
    db.commit()
    return res


@router.delete("")
def remove_all(user: User = Depends(require(P.SETTINGS_MANAGE)), db: Session = Depends(get_db)) -> dict:
    _enabled()
    n = svc.remove_all(db)
    audit.record(db, action="simulator.remove", category="system", actor=user, details={"removed": n})
    db.commit()
    return {"removed": n}


@router.post("/switches/{switch_id}/fault")
def fault(switch_id: int, body: FaultIn, user: User = Depends(require(P.SETTINGS_MANAGE)),
          db: Session = Depends(get_db)) -> dict:
    _enabled()
    sw = db.get(Switch, switch_id)
    if sw is None:
        raise not_found("Switch")
    if not sw.is_simulated:
        raise bad_request("Faults can only be injected into simulated switches")
    res = svc.inject(sw.mgmt_ip, offline=body.offline, poe_fault_port=body.poe_fault_port,
                     flapping_port=body.flapping_port, clear=body.clear)
    audit.record(db, action="simulator.fault", category="system", actor=user, switch_id=sw.id, details=body.model_dump())
    db.commit()
    return res


@router.get("/status")
def status(user: User = Depends(require(P.SWITCH_VIEW)), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    n = len(db.execute(select(Switch.id).where(Switch.is_simulated.is_(True))).all())
    return {"enabled": s.simulator_enabled, "simulated_switches": n}
