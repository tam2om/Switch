from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.api.v1.auth import user_out
from app.core.errors import forbidden
from app.core.permissions import ROLE_DESCRIPTIONS, ROLE_ORDER, P, Role, can_assign_role, permissions_for
from app.db.session import get_db
from app.models import AuditLog, User, UserRole
from app.models import Role as RoleRow
from app.services import audit
from app.services import auth as auth_service
from app.services import users as svc

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    full_name: str = Field(default="", max_length=128)
    email: EmailStr | None = None
    role: Role
    password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=128)
    email: EmailStr | None = None
    role: Role | None = None
    is_active: bool | None = None


class PasswordSet(BaseModel):
    password: str = Field(min_length=1, max_length=256)


@router.get("/roles")
def roles(user: User = Depends(require(P.USER_VIEW))) -> list[dict]:
    return [{"name": r.value, "description": ROLE_DESCRIPTIONS[r], "permissions": sorted(p.value for p in permissions_for(r)),
             "assignable": can_assign_role(user.role, r)} for r in ROLE_ORDER]


@router.get("")
def list_users(q: str | None = None, role: Role | None = None, active: bool | None = None,
               page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
               user: User = Depends(require(P.USER_VIEW)), db: Session = Depends(get_db)) -> dict:
    stmt = select(User).join(UserRole, UserRole.user_id == User.id).join(RoleRow, RoleRow.id == UserRole.role_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.username).like(like), func.lower(User.full_name).like(like),
                              func.lower(User.email).like(like)))
    if role:
        stmt = stmt.where(RoleRow.name == role.value)
    if active is not None:
        stmt = stmt.where(User.is_active.is_(active))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(User.username).offset((page - 1) * page_size).limit(page_size)).unique().scalars().all()
    items = []
    for u in rows:
        d = user_out(u)
        d["manageable"] = can_assign_role(user.role, u.role) and u.id != user.id
        items.append(d)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create(body: UserCreate, user: User = Depends(require(P.USER_MANAGE)), db: Session = Depends(get_db)) -> dict:
    if body.role == Role.SUPER_ADMIN and user.role != Role.SUPER_ADMIN:
        raise forbidden("Only a Super Admin can create Super Admin users")
    u = svc.create_user(db, user, username=body.username, full_name=body.full_name, email=body.email,
                        role=body.role.value, password=body.password, must_change_password=body.must_change_password)
    db.commit()
    return user_out(u)


@router.get("/{user_id}")
def get_one(user_id: int, user: User = Depends(require(P.USER_VIEW)), db: Session = Depends(get_db)) -> dict:
    return user_out(svc.get_user(db, user_id))


@router.patch("/{user_id}")
def update(user_id: int, body: UserUpdate, user: User = Depends(require(P.USER_MANAGE)),
           db: Session = Depends(get_db)) -> dict:
    target = svc.get_user(db, user_id)
    data = body.model_dump(exclude_unset=True)
    u = svc.update_user(db, user, target, full_name=data.get("full_name"),
                        email=data.get("email") if "email" in data else None,
                        role=data["role"].value if data.get("role") else None, is_active=data.get("is_active"))
    db.commit()
    db.refresh(u)
    return user_out(u)


@router.delete("/{user_id}")
def delete(user_id: int, user: User = Depends(require(P.USER_MANAGE)), db: Session = Depends(get_db)) -> dict:
    svc.delete_user(db, user, svc.get_user(db, user_id))
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/reset-token")
def reset_token(user_id: int, user: User = Depends(require(P.USER_MANAGE)), db: Session = Depends(get_db)) -> dict:
    target = svc.get_user(db, user_id)
    if not can_assign_role(user.role, target.role) or target.id == user.id:
        raise forbidden("You cannot reset this user's credentials")
    token = auth_service.create_reset_token(db, target, user)
    audit.record(db, action="user.reset_token_issued", category="security", actor=user, target_type="user",
                 target_id=target.id)
    db.commit()
    # Shown once to the administrator, who delivers it to the user out-of-band. Only its hash is stored.
    return {"token": token, "reset_path": f"/reset-password?token={token}", "expires_in_hours": 24}


@router.post("/{user_id}/password")
def set_password(user_id: int, body: PasswordSet, user: User = Depends(require(P.USER_MANAGE)),
                 db: Session = Depends(get_db)) -> dict:
    svc.admin_set_password(db, user, svc.get_user(db, user_id), body.password)
    db.commit()
    return {"ok": True, "must_change_password": True}


@router.post("/{user_id}/unlock")
def unlock(user_id: int, user: User = Depends(require(P.USER_MANAGE)), db: Session = Depends(get_db)) -> dict:
    svc.unlock(db, user, svc.get_user(db, user_id))
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/mfa-reset")
def mfa_reset(user_id: int, user: User = Depends(require(P.USER_MANAGE)), db: Session = Depends(get_db)) -> dict:
    svc.reset_mfa(db, user, svc.get_user(db, user_id))
    db.commit()
    return {"ok": True}


@router.get("/{user_id}/activity")
def activity(user_id: int, limit: int = Query(100, le=500), user: User = Depends(require(P.USER_VIEW)),
             db: Session = Depends(get_db)) -> list[dict]:
    target = svc.get_user(db, user_id)
    q = select(AuditLog).where(AuditLog.actor_user_id == target.id)
    if user.role != Role.SUPER_ADMIN:
        q = q.where(AuditLog.category.in_(("operational", "auth")))
    rows = db.execute(q.order_by(AuditLog.id.desc()).limit(limit)).scalars().all()
    return [{"id": r.id, "ts": r.ts, "action": r.action, "result": r.result, "category": r.category,
             "target_type": r.target_type, "target_id": r.target_id, "ip": r.ip} for r in rows]
