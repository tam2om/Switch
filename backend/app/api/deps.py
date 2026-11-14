"""Request dependencies: client address, network restriction, session auth, CSRF and permission checks."""

from __future__ import annotations

from collections.abc import Callable
from ipaddress import ip_address

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, forbidden, unauthorized
from app.core.permissions import P, has_permission
from app.core.security import constant_time_equals
from app.db.session import get_db
from app.models import User, UserSession
from app.services import auth as auth_service

SESSION_COOKIE = "anm_session"
CSRF_COOKIE = "anm_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PASSWORD_CHANGE_ALLOWED = {"/api/v1/auth/me", "/api/v1/auth/password", "/api/v1/auth/logout",
                           "/api/v1/auth/preferences"}


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    if peer is None:
        return None
    s = get_settings()
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return peer
    if any(peer_ip in n for n in s.trusted_proxy_networks):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # Right-most untrusted hop is the real client.
            for hop in reversed([h.strip() for h in fwd.split(",") if h.strip()]):
                try:
                    hip = ip_address(hop)
                except ValueError:
                    continue
                if not any(hip in n for n in s.trusted_proxy_networks):
                    return hop
            return fwd.split(",")[0].strip()
        real = request.headers.get("x-real-ip")
        if real:
            return real
    return peer


def is_allowed_network(ip: str | None) -> bool:
    if ip is None:
        return False
    try:
        addr = ip_address(ip)
    except ValueError:
        # Starlette's TestClient reports the literal peer "testclient"; accepted only in the test environment.
        return ip == "testclient" and get_settings().environment == "test"
    return any(addr in n for n in get_settings().allowed_networks)


def current_session(request: Request, db: Session = Depends(get_db)) -> UserSession:
    token = request.cookies.get(SESSION_COOKIE)
    s = auth_service.resolve_session(db, token)
    if s is None:
        raise unauthorized()
    if request.method not in SAFE_METHODS:
        header = request.headers.get(CSRF_HEADER, "")
        if not header or not constant_time_equals(header, s.csrf_token):
            raise AppError(403, "csrf_failed", "Missing or invalid CSRF token")
    request.state.session = s
    return s


def mfa_pending_session(s: UserSession = Depends(current_session)) -> UserSession:
    return s


def current_user(request: Request, s: UserSession = Depends(current_session)) -> User:
    if s.mfa_pending:
        raise unauthorized("Multi-factor verification required", "mfa_required")
    user = s.user
    if user.must_change_password and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise AppError(403, "password_change_required", "You must change your password before continuing")
    request.state.user = user
    return user


def require(*perms: P) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        for p in perms:
            if not has_permission(user.role, p):
                raise forbidden()
        return user

    return dep


def require_any(*perms: P) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        if not any(has_permission(user.role, p) for p in perms):
            raise forbidden()
        return user

    return dep
