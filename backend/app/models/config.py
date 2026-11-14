"""Configuration backups, templates and the change-job engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow


class ConfigBackup(Base):
    __tablename__ = "config_backups"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))  # manual | scheduled | pre_change | post_change | drift
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(16), default="rest")  # rest | ssh | simulator
    verify_status: Mapped[str] = mapped_column(String(16), default="unverified")  # verified | failed | unverified
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # A backup is only marked restore-tested after an actual restore has been executed and verified.
    restore_tested: Mapped[bool] = mapped_column(Boolean, default=False)
    restore_tested_at: Mapped[datetime | None] = mapped_column(nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("change_jobs.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ConfigDiff(Base):
    __tablename__ = "config_diffs"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    from_backup_id: Mapped[int] = mapped_column(ForeignKey("config_backups.id", ondelete="CASCADE"))
    to_backup_id: Mapped[int] = mapped_column(ForeignKey("config_backups.id", ondelete="CASCADE"))
    added_lines: Mapped[int] = mapped_column(Integer, default=0)
    removed_lines: Mapped[int] = mapped_column(Integer, default=0)
    expected: Mapped[bool] = mapped_column(Boolean, default=True)  # False = change not made by this app
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    __table_args__ = (UniqueConstraint("from_backup_id", "to_backup_id", name="uq_config_diffs_pair"),)


class ConfigurationTemplate(Base, TimestampMixin):
    __tablename__ = "configuration_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    operation: Mapped[str] = mapped_column(String(48))  # a registered job operation type
    params: Mapped[dict] = mapped_column(default=dict)  # default parameters for that operation
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ChangeJob(Base):
    __tablename__ = "change_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(255))
    params: Mapped[dict] = mapped_column(default=dict)
    risk: Mapped[str] = mapped_column(String(16))  # low | medium | high | critical
    risk_reasons: Mapped[list] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(24), index=True)
    # draft? pending_approval | approved | queued | running | completed | partial | failed | cancelled | rejected
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    requested_by_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    batch_size: Mapped[int] = mapped_column(Integer, default=5)
    canary: Mapped[bool] = mapped_column(Boolean, default=True)
    max_failures: Mapped[int] = mapped_column(Integer, default=1)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    acknowledged_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str] = mapped_column(Text, default="")

    results: Mapped[list[ChangeJobResult]] = relationship(back_populates="job", cascade="all, delete-orphan",
                                                          order_by="ChangeJobResult.id")
    approvals: Mapped[list[ChangeApproval]] = relationship(back_populates="job", cascade="all, delete-orphan")


class ChangeJobResult(Base):
    __tablename__ = "change_job_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("change_jobs.id", ondelete="CASCADE"), index=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    batch_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | running | success | failed | verify_failed | skipped | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    pre_backup_id: Mapped[int | None] = mapped_column(ForeignKey("config_backups.id", ondelete="SET NULL"),
                                                      nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(default=dict)

    job: Mapped[ChangeJob] = relationship(back_populates="results")
    __table_args__ = (UniqueConstraint("job_id", "switch_id", name="uq_change_job_results_target"),)


class ChangeApproval(Base):
    __tablename__ = "change_approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("change_jobs.id", ondelete="CASCADE"), index=True)
    approver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approver_name: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(16))  # approved | rejected
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    job: Mapped[ChangeJob] = relationship(back_populates="approvals")
