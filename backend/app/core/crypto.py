"""Envelope-free symmetric encryption for secrets at rest (AES-256-GCM with a key ring).

Ciphertext format (text): "v1:<key_id>:<base64url(nonce|ciphertext|tag)>".
Keys are supplied by ANM_ENCRYPTION_KEYS as "<id>:<base64url 32 bytes>,..."; the first key encrypts,
all keys decrypt, which allows rotation without downtime.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(Exception):
    pass


def generate_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")


def _b64d(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


@dataclass
class KeyRing:
    active_id: str
    keys: dict[str, bytes]

    @classmethod
    def parse(cls, spec: str) -> KeyRing:
        keys: dict[str, bytes] = {}
        active = None
        for part in [p.strip() for p in spec.split(",") if p.strip()]:
            if ":" not in part:
                raise CryptoError("Encryption key entries must be '<id>:<key>'")
            kid, raw = part.split(":", 1)
            key = _b64d(raw)
            if len(key) != 32:
                raise CryptoError(f"Encryption key '{kid}' must decode to 32 bytes")
            keys[kid] = key
            active = active or kid
        if not active:
            raise CryptoError("No encryption keys configured")
        return cls(active_id=active, keys=keys)

    def encrypt_bytes(self, data: bytes, aad: bytes = b"") -> bytes:
        nonce = os.urandom(12)
        ct = AESGCM(self.keys[self.active_id]).encrypt(nonce, data, aad or None)
        kid = self.active_id.encode()
        return b"ANM1" + bytes([len(kid)]) + kid + nonce + ct

    def decrypt_bytes(self, blob: bytes, aad: bytes = b"") -> bytes:
        if not blob.startswith(b"ANM1"):
            raise CryptoError("Unknown ciphertext format")
        klen = blob[4]
        kid = blob[5 : 5 + klen].decode()
        nonce = blob[5 + klen : 17 + klen]
        ct = blob[17 + klen :]
        key = self.keys.get(kid)
        if key is None:
            raise CryptoError(f"Key '{kid}' is not in the key ring")
        try:
            return AESGCM(key).decrypt(nonce, ct, aad or None)
        except Exception as exc:  # InvalidTag
            raise CryptoError("Decryption failed (tampered data or wrong key)") from exc

    def encrypt_str(self, value: str, aad: str = "") -> str:
        blob = self.encrypt_bytes(value.encode(), aad.encode())
        return "v1:" + base64.urlsafe_b64encode(blob).decode()

    def decrypt_str(self, token: str, aad: str = "") -> str:
        if not token.startswith("v1:"):
            raise CryptoError("Unknown secret format")
        return self.decrypt_bytes(_b64d(token[3:]), aad.encode()).decode()


_ring: KeyRing | None = None


def get_keyring() -> KeyRing:
    global _ring
    if _ring is None:
        from app.core.config import get_settings

        _ring = KeyRing.parse(get_settings().encryption_keys)
    return _ring


def reset_keyring() -> None:
    global _ring
    _ring = None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
