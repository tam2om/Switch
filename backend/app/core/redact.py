"""Secret masking for logs, audit records and error messages."""

from __future__ import annotations

import logging
import re
from typing import Any

SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "auth_key", "priv_key", "auth_password",
    "priv_password", "community", "api_key", "session_id", "sessionid", "cookie",
    "totp_secret", "private_key", "new_password", "current_password", "minio_secret_key",
    "smtp_password", "encryption_keys", "authorization", "x-csrf-token", "key",
}
MASK = "********"

_PATTERNS = [
    re.compile(r"(?i)(password|passwd|secret|community|auth-key|priv-key|key)(\s+|=|:)(\S+)"),
    re.compile(r"(?i)(sessionId=)([^;\s]+)"),
    re.compile(r"(?i)(snmpv3 user \S+ auth \S+ )(\S+)( priv \S+ )(\S+)"),
]


def _is_sensitive(key: str) -> bool:
    k = key.lower()
    return k in SENSITIVE_KEYS or any(s in k for s in ("password", "secret", "token", "_key"))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (MASK if isinstance(k, str) and _is_sensitive(k) and v not in (None, "") else redact(v))
                for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(redact(v) for v in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    out = text
    out = _PATTERNS[2].sub(lambda m: f"{m.group(1)}{MASK}{m.group(3)}{MASK}", out)
    out = _PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
    out = _PATTERNS[1].sub(lambda m: f"{m.group(1)}{MASK}", out)
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str | dict | list) else a for a in record.args) \
                if isinstance(record.args, tuple) else redact(record.args)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
