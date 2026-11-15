from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CSRF_COOKIE, SESSION_COOKIE, client_ip, current_session, current_user
from app.core.config import get_settings
from app.core.errors import bad_request
from app.core.permissions import permissions_for
from app.db.base import utcnow
from app.db.session import get_db
from app.models import User, UserSession
from app.services import audit
from app.services import auth as auth_service
from app.services import settings as sysset
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MfaIn(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(min_length=1, max_length=256)


class PreferencesIn(BaseModel):
    theme: Literal["dark", "light"] | None = None
    mode: Literal["simple", "pro"] | None = None
    refresh_seconds: int | None = Field(default=None, ge=10, le=600)


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "email": u.email, "role": u.role,
            "is_active": u.is_active, "mfa_enabled": u.mfa_enabled, "must_change_password": u.must_change_password,
            "last_login_at": u.last_login_at, "last_login_ip": u.last_login_ip, "created_at": u.created_at,
            "locked": bool(u.locked_until and u.locked_until > utcnow()),
            "preferences": u.preferences or {}}


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="strict", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="strict", path="/")


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    res = auth_service.login(db, body.username, body.password, client_ip(request), request.headers.get("user-agent"))
    _set_cookies(response, res.token, res.csrf)
    user = res.session.user
    return {"mfa_required": res.mfa_required, "csrf_token": res.csrf,
            "user": None if res.mfa_required else user_out(user)}


@router.post("/mfa/verify")
def mfa_verify(body: MfaIn, request: Request, s: UserSession = Depends(current_session),
               db: Session = Depends(get_db)) -> dict:
    auth_service.verify_mfa(db, s, body.code, client_ip(request))
    return {"user": user_out(s.user)}


@router.post("/logout")
def logout(response: Response, s: UserSession = Depends(current_session), db: Session = Depends(get_db)) -> dict:
    auth_service.logout(db, s)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    out = user_out(user)
    out["permissions"] = sorted(p.value for p in permissions_for(user.role))
    out["mfa_setup_required"] = auth_service.mfa_required_but_missing(db, user)
    s = get_settings()
    out["simulator_enabled"] = s.simulator_enabled
    out["dashboard_refresh_seconds"] = sysset.get(db, "ui.dashboard_refresh_seconds")
    out["stale_after_seconds"] = sysset.get(db, "metrics.stale_after_seconds")
    return out


@router.post("/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), s: UserSession = Depends(current_session),
                    db: Session = Depends(get_db)) -> dict:
    auth_service.change_password(db, user, body.current_password, body.new_password, s.id)
    db.commit()
    return {"ok": True}


@router.post("/reset")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)) -> dict:
    auth_service.consume_reset_token(db, body.token, body.new_password, client_ip(request))
    db.commit()
    return {"ok": True}


@router.patch("/preferences")
def preferences(body: PreferencesIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    prefs = dict(user.preferences or {})
    prefs.update({k: v for k, v in body.model_dump().items() if v is not None})
    user.preferences = prefs
    db.commit()
    return {"preferences": prefs}


@router.post("/mfa/enroll")
def mfa_enroll(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    if user.mfa_enabled:
        raise bad_request("MFA is already enabled; ask an administrator to reset it first")
    secret, uri = user_service.begin_totp_enrollment(user)
    db.commit()
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/mfa/confirm")
def mfa_confirm(body: MfaIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    user_service.confirm_totp_enrollment(db, user, body.code)
    db.commit()
    return {"mfa_enabled": True}


@router.get("/sessions")
def my_sessions(user: User = Depends(current_user), s: UserSession = Depends(current_session),
                db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None)) \
        .order_by(UserSession.last_seen_at.desc()).limit(50).all()
    return [{"id": r.id, "ip": r.ip, "user_agent": r.user_agent, "created_at": r.created_at,
             "last_seen_at": r.last_seen_at, "current": r.id == s.id} for r in rows]


@router.post("/sessions/revoke-others")
def revoke_others(user: User = Depends(current_user), s: UserSession = Depends(current_session),
                  db: Session = Depends(get_db)) -> dict:
    n = auth_service.revoke_user_sessions(db, user.id, except_session_id=s.id)
    audit.record(db, action="auth.revoke_sessions", category="auth", actor=user, details={"count": n})
    db.commit()
    return {"revoked": n}
