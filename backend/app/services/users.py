"""User management rules (enforced server-side).

* Super Admin may manage every user and assign every role.
* Admin may manage only Monitor and Viewer users and assign only those roles.
* Nobody can change their own role or disable/delete themselves (no self-escalation, no self-lockout).
* The last active Super Admin can never be disabled, demoted or deleted.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import security
from app.core.crypto import get_keyring
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.core.permissions import Role, can_assign_role
from app.models import Role as RoleRow
from app.models import User, UserRole
from app.services import audit
from app.services.auth import revoke_user_sessions, set_password


def role_row(db: Session, name: str) -> RoleRow:
    r = db.execute(select(RoleRow).where(RoleRow.name == name)).scalar_one_or_none()
    if r is None:
        raise bad_request(f"Unknown role '{name}'", "invalid_role")
    return r


def active_superadmin_count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(User).join(UserRole, UserRole.user_id == User.id)
                      .join(RoleRow, RoleRow.id == UserRole.role_id)
                      .where(RoleRow.name == Role.SUPER_ADMIN, User.is_active.is_(True))).scalar_one()


def _assert_can_manage(actor: User, target: User) -> None:
    if not can_assign_role(actor.role, target.role):
        raise forbidden("You cannot manage users with this role")


USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]{2,63}")


def create_user(db: Session, actor: User | None, *, username: str, full_name: str, email: str | None, role: str,
                password: str, must_change_password: bool = True) -> User:
    """actor=None means the local CLI (first-run setup / recovery), which requires shell access to the server."""
    if actor is not None and not can_assign_role(actor.role, role):
        raise forbidden("You cannot assign this role")
    username = username.strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise bad_request("Username must be 3-64 characters of letters, digits, '.', '_' or '-' and start with a "
                          "letter or digit", "invalid_username")
    if db.execute(select(User).where(func.lower(User.username) == username)).first():
        raise conflict("A user with this username already exists", "username_taken")
    if email and db.execute(select(User).where(func.lower(User.email) == email.lower())).first():
        raise conflict("A user with this email already exists", "email_taken")
    errors = security.password_policy_errors(password, username)
    if errors:
        raise bad_request("; ".join(errors), "weak_password", {"errors": errors})
    user = User(username=username, full_name=full_name, email=email or None,
                password_hash=security.hash_password(password), must_change_password=must_change_password,
                created_by_id=actor.id if actor else None)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role_row(db, role).id, assigned_by_id=actor.id if actor else None))
    db.flush()
    db.refresh(user)
    audit.record(db, action="user.create", category="security", actor=actor, actor_name="cli",
                 target_type="user", target_id=user.id, details={"username": username, "role": role})
    return user


def update_user(db: Session, actor: User, target: User, *, full_name: str | None = None, email: str | None = None,
                role: str | None = None, is_active: bool | None = None) -> User:
    _assert_can_manage(actor, target)
    changes: dict = {}
    if full_name is not None and full_name != target.full_name:
        changes["full_name"] = [target.full_name, full_name]
        target.full_name = full_name
    if email is not None and (email or None) != target.email:
        if email and db.execute(select(User).where(func.lower(User.email) == email.lower(), User.id != target.id)).first():
            raise conflict("A user with this email already exists", "email_taken")
        changes["email"] = [target.email, email or None]
        target.email = email or None
    if role is not None and role != target.role:
        if target.id == actor.id:
            raise forbidden("You cannot change your own role")
        if not can_assign_role(actor.role, role):
            raise forbidden("You cannot assign this role")
        if target.role == Role.SUPER_ADMIN and target.is_active and active_superadmin_count(db) <= 1:
            raise conflict("The last active Super Admin cannot be demoted", "last_superadmin")
        changes["role"] = [target.role, role]
        assert target.role_link is not None
        target.role_link.role_id = role_row(db, role).id
        target.role_link.assigned_by_id = actor.id
        revoke_user_sessions(db, target.id)
    if is_active is not None and is_active != target.is_active:
        if target.id == actor.id:
            raise forbidden("You cannot disable your own account")
        if not is_active and target.role == Role.SUPER_ADMIN and active_superadmin_count(db) <= 1:
            raise conflict("The last active Super Admin cannot be disabled", "last_superadmin")
        changes["is_active"] = [target.is_active, is_active]
        target.is_active = is_active
        if not is_active:
            revoke_user_sessions(db, target.id)
    db.flush()
    db.expire(target)
    if changes:
        audit.record(db, action="user.update", category="security", actor=actor, target_type="user",
                     target_id=target.id, details={"username": target.username, "changes": changes})
    return target


def delete_user(db: Session, actor: User, target: User) -> None:
    _assert_can_manage(actor, target)
    if target.id == actor.id:
        raise forbidden("You cannot delete your own account")
    if target.role == Role.SUPER_ADMIN and target.is_active and active_superadmin_count(db) <= 1:
        raise conflict("The last active Super Admin cannot be deleted", "last_superadmin")
    audit.record(db, action="user.delete", category="security", actor=actor, target_type="user",
                 target_id=target.id, details={"username": target.username, "role": target.role})
    db.delete(target)
    db.flush()


def admin_set_password(db: Session, actor: User, target: User, password: str) -> None:
    _assert_can_manage(actor, target)
    if target.id == actor.id:
        raise forbidden("Use the change-password page for your own account")
    set_password(db, target, password)
    target.must_change_password = True
    revoke_user_sessions(db, target.id)
    audit.record(db, action="user.password_set_by_admin", category="security", actor=actor, target_type="user",
                 target_id=target.id, details={"username": target.username})


def unlock(db: Session, actor: User, target: User) -> None:
    _assert_can_manage(actor, target)
    target.locked_until = None
    target.failed_login_count = 0
    audit.record(db, action="user.unlock", category="security", actor=actor, target_type="user",
                 target_id=target.id)


def reset_mfa(db: Session, actor: User, target: User) -> None:
    _assert_can_manage(actor, target)
    target.mfa_enabled = False
    target.totp_secret_enc = None
    revoke_user_sessions(db, target.id)
    audit.record(db, action="user.mfa_reset", category="security", actor=actor, target_type="user",
                 target_id=target.id)


def begin_totp_enrollment(user: User) -> tuple[str, str]:
    secret = security.new_totp_secret()
    user.totp_secret_enc = get_keyring().encrypt_str(secret, f"totp:{user.id}")
    user.mfa_enabled = False
    return secret, security.totp_uri(secret, user.username)


def confirm_totp_enrollment(db: Session, user: User, code: str) -> None:
    if not user.totp_secret_enc:
        raise bad_request("Start MFA enrollment first")
    secret = get_keyring().decrypt_str(user.totp_secret_enc, f"totp:{user.id}")
    if not security.verify_totp(secret, code):
        raise bad_request("Invalid verification code", "invalid_mfa")
    user.mfa_enabled = True
    audit.record(db, action="user.mfa_enabled", category="security", actor=user, target_type="user", target_id=user.id)


def get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise not_found("User")
    return u
