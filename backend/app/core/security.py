"""Password hashing (Argon2id), token generation, TOTP and password policy."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings

# OWASP-recommended Argon2id parameters (m=64MiB, t=3, p=4).
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

# A dummy hash used to equalise timing when the user does not exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

COMMON_PASSWORDS = {
    "password", "password123", "admin", "admin123", "administrator", "changeme", "letmein", "welcome",
    "qwerty", "123456", "12345678", "123456789", "1234567890", "manager", "aruba", "procurve", "switch",
    "passw0rd", "p@ssw0rd", "iloveyou", "secret",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def password_policy_errors(password: str, username: str = "") -> list[str]:
    s = get_settings()
    errors: list[str] = []
    if len(password) < s.password_min_length:
        errors.append(f"Password must be at least {s.password_min_length} characters")
    if len(password) > 256:
        errors.append("Password must be at most 256 characters")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^A-Za-z0-9]"))
    if classes < 3:
        errors.append("Password must contain at least three of: lowercase, uppercase, digits, symbols")
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or any(lowered.startswith(c) and len(lowered) - len(c) <= 3
                                          for c in COMMON_PASSWORDS if len(c) >= 6):
        errors.append("Password is too common")
    if username and username.lower() in lowered:
        errors.append("Password must not contain the username")
    return errors


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """Session tokens are stored as keyed hashes so a database leak does not expose live sessions."""
    secret = get_settings().session_secret.encode() or b"anm"
    return hmac.new(secret, token.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, username: str, issuer: str = "Aruba Network Manager") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    return pyotp.TOTP(secret).verify(code, valid_window=1)
