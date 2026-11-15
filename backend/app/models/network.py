"""VLAN, PoE, monitoring time-series and connected-device models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, utcnow


class Vlan(Base, TimestampMixin):
    """Fleet-wide VLAN catalogue (the intended VLAN plan)."""

    __tablename__ = "vlans"
    id: Mapped[int] = mapped_column(primary_key=True)
    vlan_id: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(255), default="")
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)
    is_voice: Mapped[bool] = mapped_column(Boolean, default=False)


class SwitchVlan(Base):
    """VLANs actually configured on a switch (as last read from the device)."""

    __tablename__ = "switch_vlans"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    vlan_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="port_based")
    is_management: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("switch_id", "vlan_id", name="uq_switch_vlans_vid"),)


class PortVlanMembership(Base):
    __tablename__ = "port_vlan_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    port_name: Mapped[str] = mapped_column(String(32))
    vlan_id: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(10))  # tagged | untagged
    __table_args__ = (UniqueConstraint("switch_id", "port_name", "vlan_id", name="uq_pvm_port_vlan"),)


class PortConfiguration(Base):
    """Last-applied port configuration via this application (for drift detection and history)."""

    __tablename__ = "port_configurations"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    port_name: Mapped[str] = mapped_column(String(32))
    settings: Mapped[dict] = mapped_column(default=dict)
    applied_at: Mapped[datetime] = mapped_column(default=utcnow)
    applied_by_job_id: Mapped[int | None] = mapped_column(ForeignKey("change_jobs.id", ondelete="SET NULL"),
                                                          nullable=True)
    __table_args__ = (UniqueConstraint("switch_id", "port_name", name="uq_port_configurations_port"),)


class PoeConfiguration(Base):
    """Per-port PoE state as last read from the device."""

    __tablename__ = "poe_configurations"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    port_name: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    priority: Mapped[str | None] = mapped_column(String(16), nullable=True)  # low | high | critical
    allocation_method: Mapped[str | None] = mapped_column(String(16), nullable=True)  # usage | class | value
    allocated_power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    power_drawn_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    detection_status: Mapped[str | None] = mapped_column(String(32), nullable=True)  # delivering, searching, fault
    power_class: Mapped[str | None] = mapped_column(String(8), nullable=True)
    fault: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    __table_args__ = (UniqueConstraint("switch_id", "port_name", name="uq_poe_configurations_port"),)


# ---------- time-series (TimescaleDB hypertables when the extension is available) ----------


class SwitchMetric(Base):
    __tablename__ = "switch_metrics"
    switch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    reachable: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    poe_consumed_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    poe_budget_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (Index("ix_switch_metrics_ts", "ts"),)


class PortMetric(Base):
    __tablename__ = "port_metrics"
    switch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    if_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    oper_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    in_octets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_octets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_errors: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_errors: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    in_discards: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_discards: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    __table_args__ = (Index("ix_port_metrics_ts", "ts"),)


class PoeMetric(Base):
    __tablename__ = "poe_metrics"
    switch_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    port_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    power_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    __table_args__ = (Index("ix_poe_metrics_ts", "ts"),)


class SwitchEvent(Base):
    __tablename__ = "switch_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    switch_id: Mapped[int | None] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), nullable=True,
                                                  index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")  # info warning major critical
    type: Mapped[str] = mapped_column(String(48), index=True)
    port_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(default=dict)


class MacLearnedEntry(Base):
    __tablename__ = "mac_learned_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    mac: Mapped[str] = mapped_column(String(17), index=True)
    vlan_id: Mapped[int] = mapped_column(Integer)
    port_name: Mapped[str] = mapped_column(String(32))
    vendor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (UniqueConstraint("switch_id", "mac", "vlan_id", name="uq_mac_entries_switch_mac_vlan"),)


class OuiVendor(Base):
    __tablename__ = "oui_vendors"
    prefix: Mapped[str] = mapped_column(String(8), primary_key=True)  # "AA:BB:CC"
    vendor: Mapped[str] = mapped_column(String(128))


__all__ = ["Vlan", "SwitchVlan", "PortVlanMembership", "PortConfiguration", "PoeConfiguration", "SwitchMetric",
           "PortMetric", "PoeMetric", "SwitchEvent", "MacLearnedEntry", "OuiVendor", "Text"]
