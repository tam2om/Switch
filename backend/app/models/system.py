"""Alerts, notifications, settings, polling schedule and integrations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, utcnow


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    params: Mapped[dict] = mapped_column(default=dict)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    recipients: Mapped[list] = mapped_column(default=list)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(16))
    switch_id: Mapped[int | None] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), nullable=True,
                                                  index=True)
    port_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active acknowledged resolved
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(default=dict)
    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"),
                                                           nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("uq_alerts_open_dedup", "dedup_key", unique=True, postgresql_where="status <> 'resolved'"),
    )


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="email")
    recipient: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending sent failed
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    category: Mapped[str] = mapped_column(String(16))  # security | operational
    value: Mapped[dict] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class PollingJob(Base):
    __tablename__ = "polling_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(32), unique=True)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="never")
    last_error: Mapped[str] = mapped_column(Text, default="")
    switches_polled: Mapped[int] = mapped_column(Integer, default=0)
    switches_failed: Mapped[int] = mapped_column(Integer, default=0)


class IntegrationSetting(Base, TimestampMixin):
    __tablename__ = "integration_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), unique=True)  # zabbix | airwave
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(255), default="")
    username: Mapped[str] = mapped_column(String(64), default="")
    secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=True)
    params: Mapped[dict] = mapped_column(default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="never")
    last_message: Mapped[str] = mapped_column(Text, default="")
