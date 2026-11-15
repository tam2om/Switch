"""Encrypted device credential storage and resolution.

Resolution order for (switch, kind, purpose): switch-specific credential, then fleet default (switch_id NULL).
Configuration operations use 'config' credentials; monitoring uses 'monitor' credentials. A 'config' lookup
never silently falls back to monitoring credentials, and vice versa (least privilege).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import get_keyring
from app.models import SwitchCredential

SECRET_FIELDS = {
    "rest": ("password",),
    "ssh": ("password",),
    "snmpv3": ("auth_password", "priv_password"),
}
PARAM_FIELDS = {
    "rest": (),
    "ssh": ("port",),
    "snmpv3": ("auth_protocol", "priv_protocol"),
}


def _aad(kind: str) -> str:
    return f"switch-credential:{kind}"


def encrypt_secret(kind: str, secrets: dict) -> str:
    return get_keyring().encrypt_str(json.dumps(secrets), _aad(kind))


def decrypt_secret(cred: SwitchCredential) -> dict:
    return json.loads(get_keyring().decrypt_str(cred.secret_enc, _aad(cred.kind)))


def upsert(db: Session, *, switch_id: int | None, kind: str, purpose: str, username: str, secrets: dict,
           params: dict | None = None, name: str = "") -> SwitchCredential:
    if kind not in SECRET_FIELDS:
        raise ValueError(f"Unknown credential kind {kind}")
    missing = [f for f in SECRET_FIELDS[kind] if not secrets.get(f)]
    if missing:
        raise ValueError(f"Missing secret fields: {', '.join(missing)}")
    cred = db.execute(select(SwitchCredential).where(
        SwitchCredential.switch_id.is_(None) if switch_id is None else SwitchCredential.switch_id == switch_id,
        SwitchCredential.kind == kind, SwitchCredential.purpose == purpose)).scalar_one_or_none()
    payload = {f: secrets[f] for f in SECRET_FIELDS[kind]}
    if cred is None:
        cred = SwitchCredential(switch_id=switch_id, kind=kind, purpose=purpose, username=username,
                                name=name or f"{kind}-{purpose}", params=params or {},
                                secret_enc=encrypt_secret(kind, payload))
        db.add(cred)
    else:
        cred.username = username
        cred.params = params or {}
        cred.secret_enc = encrypt_secret(kind, payload)
        if name:
            cred.name = name
    db.flush()
    return cred


def resolve(db: Session, switch_id: int, kind: str, purpose: str) -> tuple[str, dict, dict] | None:
    rows = db.execute(select(SwitchCredential).where(
        SwitchCredential.kind == kind, SwitchCredential.purpose == purpose,
        (SwitchCredential.switch_id == switch_id) | SwitchCredential.switch_id.is_(None))).scalars().all()
    if not rows:
        return None
    cred = sorted(rows, key=lambda c: c.switch_id is None)[0]
    return cred.username, decrypt_secret(cred), cred.params or {}


def public_view(cred: SwitchCredential) -> dict:
    return {"id": cred.id, "switch_id": cred.switch_id, "name": cred.name, "kind": cred.kind,
            "purpose": cred.purpose, "username": cred.username, "params": cred.params,
            "secret": "********", "updated_at": cred.updated_at}
