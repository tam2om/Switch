from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import bad_request
from app.core.permissions import P
from app.db.session import get_db
from app.integrations import service
from app.integrations.zabbix import IntegrationError
from app.models import User
from app.services import audit

router = APIRouter(prefix="/integrations", tags=["integrations"])


class IntegrationIn(BaseModel):
    enabled: bool = False
    url: str = Field(default="", max_length=255)
    username: str = Field(default="", max_length=64)
    secret: str | None = Field(default=None, max_length=512)
    verify_tls: bool = True
    params: dict = Field(default_factory=dict)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not v.startswith("https://"):
            raise ValueError("Integration URLs must use HTTPS")
        return v


def _kind(kind: str) -> str:
    if kind not in service.KINDS:
        raise bad_request("Unknown integration")
    return kind


@router.get("")
def list_integrations(user: User = Depends(require(P.INTEGRATION_MANAGE)), db: Session = Depends(get_db)) -> list[dict]:
    out = [service.public(service.get_or_create(db, k)) for k in service.KINDS]
    db.commit()
    return out


@router.put("/{kind}")
def update(kind: str, body: IntegrationIn, user: User = Depends(require(P.INTEGRATION_MANAGE)),
           db: Session = Depends(get_db)) -> dict:
    row = service.get_or_create(db, _kind(kind))
    row.enabled, row.url, row.username, row.verify_tls, row.params = (body.enabled, body.url, body.username,
                                                                      body.verify_tls, body.params)
    if body.secret:
        service.set_secret(row, body.secret)
    audit.record(db, action="integration.update", category="security", actor=user, target_type="integration",
                 target_id=kind, details={"enabled": body.enabled, "url": body.url, "secret_changed": bool(body.secret)})
    db.commit()
    return service.public(row)


@router.post("/{kind}/test")
def test(kind: str, user: User = Depends(require(P.INTEGRATION_MANAGE)), db: Session = Depends(get_db)) -> dict:
    try:
        return service.test(db, _kind(kind))
    except IntegrationError as exc:
        return {"ok": False, "error": str(exc)}


@router.get("/{kind}/preview")
def preview(kind: str, user: User = Depends(require(P.INTEGRATION_MANAGE)), db: Session = Depends(get_db)) -> list[dict]:
    try:
        return service.preview(db, _kind(kind))
    except IntegrationError as exc:
        raise bad_request(str(exc), "integration_error") from exc


@router.post("/{kind}/sync")
def sync(kind: str, import_new: bool = False, user: User = Depends(require(P.INTEGRATION_MANAGE)),
         db: Session = Depends(get_db)) -> dict:
    res = service.sync(db, _kind(kind), import_new=import_new)
    audit.record(db, action="integration.sync", actor=user, target_type="integration", target_id=kind, details=res)
    db.commit()
    return res
