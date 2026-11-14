"""Application settings, loaded from environment variables.

No secret has a default value. The application refuses to start in production mode
when required secrets are missing or obviously weak.
"""

from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_network
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANM_", env_file=".env", extra="ignore")

    environment: Literal["production", "development", "test"] = "production"
    app_name: str = "Aruba Network Manager"

    database_url: str = Field(default="postgresql+psycopg://anm@localhost:5432/anm")
    redis_url: str = "redis://localhost:6379/0"

    # 32-byte url-safe base64 keys. Key ring format: "<id>:<key>,<id>:<key>"; the first is active.
    encryption_keys: str = ""
    session_secret: str = ""

    # Object storage for configuration backups.
    storage_backend: Literal["minio", "filesystem"] = "minio"
    storage_path: str = "/var/lib/anm/backups"
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "anm-config-backups"
    minio_secure: bool = False

    # Session / auth policy.
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    login_rate_per_minute: int = 10
    password_min_length: int = 12
    cookie_secure: bool = True

    # Network access restriction (applied by middleware in addition to firewall/Nginx).
    allowed_client_networks: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128"
    trusted_proxies: str = "127.0.0.1/32,172.16.0.0/12"
    cors_origins: str = ""

    # Device communication.
    device_timeout_seconds: float = 10.0
    device_max_retries: int = 2
    poll_concurrency: int = 16
    rest_verify_tls: bool = True
    rest_ca_bundle: str = ""

    # Demo / simulator mode. Simulated switches are always labelled in the UI and API.
    simulator_enabled: bool = False

    smtp_host: str = ""
    smtp_port: int = 25
    smtp_starttls: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "anm@localhost"

    @field_validator("allowed_client_networks", "trusted_proxies")
    @classmethod
    def _validate_networks(cls, v: str) -> str:
        for item in [x.strip() for x in v.split(",") if x.strip()]:
            ip_network(item, strict=False)
        return v

    @property
    def allowed_networks(self):
        return [ip_network(x.strip(), strict=False) for x in self.allowed_client_networks.split(",") if x.strip()]

    @property
    def trusted_proxy_networks(self):
        return [ip_network(x.strip(), strict=False) for x in self.trusted_proxies.split(",") if x.strip()]

    def validate_for_runtime(self) -> list[str]:
        problems: list[str] = []
        if not self.encryption_keys:
            problems.append("ANM_ENCRYPTION_KEYS is not set")
        if len(self.session_secret) < 32:
            problems.append("ANM_SESSION_SECRET must be at least 32 characters")
        if self.storage_backend == "minio" and (not self.minio_access_key or not self.minio_secret_key):
            problems.append("MinIO credentials are not set")
        if self.environment == "production" and not self.cookie_secure:
            problems.append("ANM_COOKIE_SECURE must be true in production")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
