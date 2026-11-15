"""Runtime-tunable system settings stored in the database.

category 'security'    -> only Super Admin may change (SETTINGS_MANAGE)
category 'operational' -> Admin may change (OPERATIONAL_SETTINGS_MANAGE)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import SystemSetting

DEFAULTS: dict[str, tuple[str, Any, str]] = {
    # key: (category, default, description)
    "auth.session_idle_minutes": ("security", 30, "Idle session timeout (minutes)"),
    "auth.session_absolute_hours": ("security", 12, "Absolute session lifetime (hours)"),
    "auth.max_failed_logins": ("security", 5, "Failed logins before lockout"),
    "auth.lockout_minutes": ("security", 15, "Account lockout duration (minutes)"),
    "auth.require_mfa_for_admins": ("security", False, "Require TOTP MFA for Super Admin and Admin"),
    "auth.password_max_age_days": ("security", 0, "Force password change after N days (0 = never)"),
    "changes.allow_self_approval": ("security", False,
                                    "Allow a Super Admin to approve their own high-risk change (single-admin sites)"),
    "changes.require_approval_risk": ("security", "high", "Lowest risk level that requires approval"),
    "audit.retention_days": ("security", 730, "Audit log retention (days, minimum 365)"),
    "polling.availability_seconds": ("operational", 30, "Availability / port status polling interval"),
    "polling.counters_seconds": ("operational", 60, "Interface counters polling interval"),
    "polling.health_seconds": ("operational", 60, "CPU / memory polling interval"),
    "polling.poe_seconds": ("operational", 60, "PoE polling interval"),
    "polling.temperature_seconds": ("operational", 300, "Temperature polling interval"),
    "polling.mac_seconds": ("operational", 300, "MAC table polling interval"),
    "polling.lldp_seconds": ("operational", 300, "LLDP polling interval"),
    "polling.inventory_seconds": ("operational", 3600, "Inventory / VLAN / config sync interval"),
    "backups.schedule_hour": ("operational", 2, "Hour of day (server time) for scheduled backups"),
    "backups.enabled": ("operational", True, "Enable scheduled daily configuration backups"),
    "backups.retention_count": ("operational", 60, "Backups to keep per switch (pre-change backups always kept 90 days)"),
    "jobs.default_batch_size": ("operational", 5, "Default bulk-operation batch size"),
    "alerts.cpu_threshold": ("operational", 85, "High CPU threshold (%)"),
    "alerts.memory_threshold": ("operational", 90, "High memory threshold (%)"),
    "alerts.poe_threshold": ("operational", 85, "High PoE utilisation threshold (%)"),
    "alerts.error_rate_threshold": ("operational", 10, "Interface errors per minute threshold"),
    "alerts.flap_threshold": ("operational", 4, "Link state changes within 10 minutes to declare flapping"),
    "ui.dashboard_refresh_seconds": ("operational", 30, "Default dashboard refresh interval"),
    "metrics.stale_after_seconds": ("operational", 180, "Measurements older than this are shown as stale"),
}


def get(db: Session, key: str) -> Any:
    row = db.get(SystemSetting, key)
    if row is not None:
        return row.value.get("v")
    return DEFAULTS[key][1]


def all_settings(db: Session) -> list[dict]:
    rows = {r.key: r for r in db.query(SystemSetting).all()}
    out = []
    for key, (cat, default, desc) in DEFAULTS.items():
        r = rows.get(key)
        out.append({"key": key, "category": cat, "value": r.value.get("v") if r else default, "default": default,
                    "description": desc, "updated_at": r.updated_at if r else None})
    return out


def validate(key: str, value: Any) -> Any:
    if key not in DEFAULTS:
        raise ValueError(f"Unknown setting {key}")
    default = DEFAULTS[key][1]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{key} must be a number")
        value = int(value)
        if key.startswith("polling.") and not 15 <= value <= 86400:
            raise ValueError("Polling intervals must be between 15 seconds and 24 hours")
        if key == "audit.retention_days" and value < 365:
            raise ValueError("Audit retention must be at least 365 days")
        if key == "auth.max_failed_logins" and not 3 <= value <= 20:
            raise ValueError("Failed login threshold must be 3-20")
        if key == "auth.session_idle_minutes" and not 5 <= value <= 240:
            raise ValueError("Idle timeout must be 5-240 minutes")
        if key == "auth.session_absolute_hours" and not 1 <= value <= 24:
            raise ValueError("Session lifetime must be 1-24 hours")
        if key == "backups.schedule_hour" and not 0 <= value <= 23:
            raise ValueError("Hour must be 0-23")
        if value < 0:
            raise ValueError(f"{key} must not be negative")
        return value
    if key == "changes.require_approval_risk" and value not in ("medium", "high", "critical"):
        raise ValueError("Approval threshold must be medium, high or critical")
    return value


def set_value(db: Session, key: str, value: Any, user_id: int | None) -> None:
    value = validate(key, value)
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, category=DEFAULTS[key][0], value={"v": value}, updated_by_id=user_id))
    else:
        row.value = {"v": value}
        row.updated_by_id = user_id
    db.flush()


def category(key: str) -> str:
    return DEFAULTS[key][0]
