"""Authentication: login with throttling and lockout, server-side sessions, TOTP MFA, password resets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.config import get_settings
from app.core.crypto import get_keyring
from app.core.errors import AppError, bad_request, unauthorized
from app.core.permissions import Role
from app.db.base import utcnow
from app.models import LoginAttempt, PasswordResetToken, User, UserSession
from app.services import audit
from app.services import settings as sysset

GENERIC_LOGIN_ERROR = "Invalid username or password"


@dataclass
class LoginResult:
    token: str
    csrf: str
    session: UserSession
    mfa_required: bool


def _throttled(db: Session, ip: str | None) -> bool:
    if not ip:
        return False
    since = utcnow() - timedelta(minutes=1)
    n = db.execute(select(func.count()).select_from(LoginAttempt).where(
        LoginAttempt.ip == ip, LoginAttempt.ts >= since, LoginAttempt.success.is_(False))).scalar_one()
    return n >= get_settings().login_rate_per_minute


def _attempt(db: Session, username: str, ip: str | None, success: bool, reason: str = "") -> None:
    db.add(LoginAttempt(username=username[:64], ip=ip, success=success, reason=reason))


def create_session(db: Session, user: User, ip: str | None, ua: str | None, mfa_pending: bool) -> LoginResult:
    token = security.new_token()
    csrf = security.new_token(24)
    hours = int(sysset.get(db, "auth.session_absolute_hours"))
    s = UserSession(token_hash=security.token_hash(token), csrf_token=csrf, user_id=user.id,
                    expires_at=utcnow() + timedelta(hours=hours), ip=ip, user_agent=(ua or "")[:255],
                    mfa_pending=mfa_pending)
    db.add(s)
    db.flush()
    return LoginResult(token=token, csrf=csrf, session=s, mfa_required=mfa_pending)


def login(db: Session, username: str, password: str, ip: str | None, ua: str | None) -> LoginResult:
    username = (username or "").strip().lower()
    if _throttled(db, ip):
        _attempt(db, username, ip, False, "rate_limited")
        audit.record(db, action="auth.login", category="auth", actor_name=username, result="denied", ip=ip,
                     details={"reason": "rate_limited"})
        db.commit()
        raise AppError(429, "rate_limited", "Too many login attempts. Try again in a minute.")
    user = db.execute(select(User).where(func.lower(User.username) == username)).unique().scalar_one_or_none()
    ok = security.verify_password(user.password_hash if user else None, password or "")
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        _attempt(db, username, ip, False, "locked")
        audit.record(db, action="auth.login", category="auth", actor=user, result="denied", ip=ip,
                     details={"reason": "account_locked"})
        db.commit()
        raise AppError(423, "account_locked", "Account is temporarily locked. Try again later or contact an administrator.")
    if not user or not ok:
        _attempt(db, username, ip, False, "bad_credentials")
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= int(sysset.get(db, "auth.max_failed_logins")):
                user.locked_until = now + timedelta(minutes=int(sysset.get(db, "auth.lockout_minutes")))
                user.failed_login_count = 0
                audit.record(db, action="auth.lockout", category="security", actor=user, result="success", ip=ip)
        audit.record(db, action="auth.login", category="auth", actor_name=username, result="failure", ip=ip,
                     details={"reason": "bad_credentials"})
        db.commit()
        raise unauthorized(GENERIC_LOGIN_ERROR, "invalid_credentials")
    if not user.is_active:
        _attempt(db, username, ip, False, "inactive")
        audit.record(db, action="auth.login", category="auth", actor=user, result="denied", ip=ip,
                     details={"reason": "inactive"})
        db.commit()
        raise unauthorized(GENERIC_LOGIN_ERROR, "invalid_credentials")
    if security.needs_rehash(user.password_hash):
        user.password_hash = security.hash_password(password)
    user.failed_login_count = 0
    user.locked_until = None
    _attempt(db, username, ip, True)
    res = create_session(db, user, ip, ua, mfa_pending=user.mfa_enabled)
    if not user.mfa_enabled:
        _finish_login(db, user, ip)
    audit.record(db, action="auth.login", category="auth", actor=user, ip=ip,
                 details={"mfa_pending": user.mfa_enabled})
    db.commit()
    return res


def _finish_login(db: Session, user: User, ip: str | None) -> None:
    user.last_login_at = utcnow()
    user.last_login_ip = ip


def verify_mfa(db: Session, session: UserSession, code: str, ip: str | None) -> None:
    user = session.user
    if not session.mfa_pending:
        raise bad_request("MFA is not pending for this session")
    if not user.totp_secret_enc or not security.verify_totp(
            get_keyring().decrypt_str(user.totp_secret_enc, f"totp:{user.id}"), code):
        user.failed_login_count += 1
        if user.failed_login_count >= int(sysset.get(db, "auth.max_failed_logins")):
            user.locked_until = utcnow() + timedelta(minutes=int(sysset.get(db, "auth.lockout_minutes")))
            user.failed_login_count = 0
            session.revoked_at = utcnow()
        audit.record(db, action="auth.mfa", category="auth", actor=user, result="failure", ip=ip)
        db.commit()
        raise unauthorized("Invalid verification code", "invalid_mfa")
    session.mfa_pending = False
    user.failed_login_count = 0
    _finish_login(db, user, ip)
    audit.record(db, action="auth.mfa", category="auth", actor=user, ip=ip)
    db.commit()


def resolve_session(db: Session, token: str | None) -> UserSession | None:
    if not token:
        return None
    s = db.execute(select(UserSession).where(UserSession.token_hash == security.token_hash(token))) \
        .unique().scalar_one_or_none()
    if s is None or s.revoked_at is not None:
        return None
    now = utcnow()
    idle = int(sysset.get(db, "auth.session_idle_minutes"))
    if s.expires_at <= now or s.last_seen_at + timedelta(minutes=idle) <= now:
        s.revoked_at = now
        db.commit()
        return None
    if not s.user.is_active:
        s.revoked_at = now
        db.commit()
        return None
    # Throttle last_seen writes to once a minute.
    if (now - s.last_seen_at).total_seconds() > 60:
        s.last_seen_at = now
        db.commit()
    return s


def logout(db: Session, session: UserSession) -> None:
    session.revoked_at = utcnow()
    audit.record(db, action="auth.logout", category="auth", actor=session.user, ip=session.ip)
    db.commit()


def revoke_user_sessions(db: Session, user_id: int, except_session_id: int | None = None) -> int:
    q = db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    if except_session_id:
        q = q.filter(UserSession.id != except_session_id)
    n = 0
    for s in q.all():
        s.revoked_at = utcnow()
        n += 1
    return n


def change_password(db: Session, user: User, current: str, new: str, session_id: int | None) -> None:
    if not security.verify_password(user.password_hash, current):
        audit.record(db, action="user.password_change", category="security", actor=user, result="failure")
        db.commit()
        raise bad_request("Current password is incorrect", "invalid_password")
    set_password(db, user, new)
    revoke_user_sessions(db, user.id, except_session_id=session_id)
    audit.record(db, action="user.password_change", category="security", actor=user, target_type="user",
                 target_id=user.id)


def set_password(db: Session, user: User, new: str) -> None:
    errors = security.password_policy_errors(new, user.username)
    if errors:
        raise bad_request("; ".join(errors), "weak_password", {"errors": errors})
    if security.verify_password(user.password_hash, new):
        raise bad_request("New password must differ from the current password", "weak_password")
    user.password_hash = security.hash_password(new)
    user.password_changed_at = utcnow()
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None


def create_reset_token(db: Session, user: User, created_by: User, hours: int = 24) -> str:
    token = security.new_token()
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id,
                                        PasswordResetToken.used_at.is_(None)).update({"used_at": utcnow()})
    db.add(PasswordResetToken(token_hash=security.token_hash(token), user_id=user.id, created_by_id=created_by.id,
                              expires_at=utcnow() + timedelta(hours=hours)))
    return token


def consume_reset_token(db: Session, token: str, new_password: str, ip: str | None) -> User:
    row = db.execute(select(PasswordResetToken).where(
        PasswordResetToken.token_hash == security.token_hash(token or ""))).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at <= utcnow():
        raise bad_request("This reset link is invalid or has expired", "invalid_token")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise bad_request("This reset link is invalid or has expired", "invalid_token")
    set_password(db, user, new_password)
    row.used_at = utcnow()
    revoke_user_sessions(db, user.id)
    audit.record(db, action="user.password_reset_completed", category="security", actor=user, ip=ip,
                 target_type="user", target_id=user.id)
    return user


def mfa_required_but_missing(db: Session, user: User) -> bool:
    return bool(sysset.get(db, "auth.require_mfa_for_admins")) and user.role in (Role.SUPER_ADMIN, Role.ADMIN) \
        and not user.mfa_enabled
