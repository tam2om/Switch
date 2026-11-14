"""Encrypted object storage for configuration backups (MinIO/S3 or local filesystem).

Objects are encrypted with AES-256-GCM before they leave the application (the storage key is bound as
associated data, so an object cannot be swapped for another). Storage never sees plaintext configurations.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.crypto import get_keyring

_KEY_RE = re.compile(r"^[A-Za-z0-9/_.\-]{1,255}$")


class ObjectStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def health(self) -> dict: ...


class FilesystemStore:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, key: str) -> Path:
        if not _KEY_RE.match(key) or ".." in key:
            raise ValueError("invalid storage key")
        return self.root / key

    def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        tmp.replace(p)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def health(self) -> dict:
        return {"backend": "filesystem", "ok": self.root.exists() and os.access(self.root, os.W_OK)}


class MinioStore:  # pragma: no cover - exercised in the docker-compose deployment test
    def __init__(self) -> None:
        from minio import Minio

        s = get_settings()
        self.bucket = s.minio_bucket
        self.client = Minio(s.minio_endpoint, access_key=s.minio_access_key, secret_key=s.minio_secret_key,
                            secure=s.minio_secure)
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def put(self, key: str, data: bytes) -> None:
        self.client.put_object(self.bucket, key, io.BytesIO(data), length=len(data),
                               content_type="application/octet-stream")

    def get(self, key: str) -> bytes:
        r = self.client.get_object(self.bucket, key)
        try:
            return r.read()
        finally:
            r.close()
            r.release_conn()

    def delete(self, key: str) -> None:
        self.client.remove_object(self.bucket, key)

    def health(self) -> dict:
        try:
            return {"backend": "minio", "ok": self.client.bucket_exists(self.bucket)}
        except Exception as exc:  # noqa: BLE001
            return {"backend": "minio", "ok": False, "error": exc.__class__.__name__}


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = MinioStore() if s.storage_backend == "minio" else FilesystemStore(s.storage_path)
    return _store


def reset_store() -> None:
    global _store
    _store = None


def put_encrypted(key: str, plaintext: bytes) -> int:
    blob = get_keyring().encrypt_bytes(plaintext, key.encode())
    get_store().put(key, blob)
    return len(blob)


def get_decrypted(key: str) -> bytes:
    return get_keyring().decrypt_bytes(get_store().get(key), key.encode())
