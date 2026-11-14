from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow


class Site(Base, TimestampMixin):
    __tablename__ = "sites"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    address: Mapped[str] = mapped_column(String(255), default="")
    description: Mapped[str] = mapped_column(String(255), default="")


class SwitchModel(Base):
    __tablename__ = "switch_models"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_number: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. JL356A
    name: Mapped[str] = mapped_column(String(128))
    family: Mapped[str] = mapped_column(String(32), default="aos-switch")
    access_ports: Mapped[int] = mapped_column(Integer, default=24)
    uplink_ports: Mapped[int] = mapped_column(Integer, default=4)
    poe_budget_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    port_layout: Mapped[dict] = mapped_column(default=dict)
    # True only when the layout has been confirmed against a physical unit.
    hardware_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class SwitchGroup(Base, TimestampMixin):
    __tablename__ = "switch_groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")


class SwitchGroupMember(Base):
    __tablename__ = "switch_group_members"
    group_id: Mapped[int] = mapped_column(ForeignKey("switch_groups.id", ondelete="CASCADE"), primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), primary_key=True)


class Switch(Base, TimestampMixin):
    __tablename__ = "switches"
    id: Mapped[int] = mapped_column(primary_key=True)
    hostname: Mapped[str] = mapped_column(String(128), index=True)
    mgmt_ip: Mapped[str] = mapped_column(String(64), unique=True)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("switch_models.id", ondelete="SET NULL"), nullable=True)
    product_number: Mapped[str | None] = mapped_column(String(32), nullable=True)  # as reported by device
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_mac: Mapped[str | None] = mapped_column(String(17), nullable=True)
    firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rom_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"), nullable=True)
    location: Mapped[str] = mapped_column(String(128), default="")
    building: Mapped[str] = mapped_column(String(64), default="")
    floor: Mapped[str] = mapped_column(String(32), default="")
    department: Mapped[str] = mapped_column(String(64), default="")
    mgmt_vlan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uplink_ports: Mapped[list] = mapped_column(default=list)  # physical port names treated as uplinks
    driver: Mapped[str] = mapped_column(String(32), default="aruba_aos_s")  # aruba_aos_s | simulator
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    monitoring_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    protocols: Mapped[dict] = mapped_column(default=lambda: {"rest": True, "snmp": True, "ssh": True})
    rest_api_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown", index=True)  # online offline warning unknown
    status_reason: Mapped[str] = mapped_column(String(255), default="")
    last_poll_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    poe_budget_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    poe_consumed_w: Mapped[float | None] = mapped_column(Float, nullable=True)
    metrics_at: Mapped[datetime | None] = mapped_column(nullable=True)
    capabilities: Mapped[dict] = mapped_column(default=dict)
    ssh_host_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    ssh_host_key_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ssh_host_key_trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_config_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    external_ids: Mapped[dict] = mapped_column(default=dict)  # {"zabbix": "10084", "airwave": "12"}

    site: Mapped[Site | None] = relationship(lazy="joined")
    model: Mapped[SwitchModel | None] = relationship(lazy="joined")


class SwitchCredential(Base, TimestampMixin):
    """Device credentials. switch_id NULL means fleet default. Secrets are AES-GCM encrypted in secret_enc."""

    __tablename__ = "switch_credentials"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int | None] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), nullable=True,
                                                  index=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # snmpv3 | rest | ssh
    purpose: Mapped[str] = mapped_column(String(16), default="monitor")  # monitor | config
    username: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(default=dict)  # non-secret: auth_protocol, priv_protocol, port
    secret_enc: Mapped[str] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("switch_id", "kind", "purpose", name="uq_switch_credentials_scope"),)


class SwitchPort(Base):
    __tablename__ = "switch_ports"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"))
    if_index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(32))  # AOS-S port id, e.g. "1", "25", "Trk1"
    port_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    port_type: Mapped[str] = mapped_column(String(32), default="")  # 100/1000T, SFP+ ...
    is_uplink: Mapped[bool] = mapped_column(Boolean, default=False)
    trunk_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    admin_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    oper_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    speed_mbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplex: Mapped[str | None] = mapped_column(String(8), nullable=True)
    config_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)  # auto, 100-full, ...
    untagged_vlan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tagged_vlans: Mapped[list] = mapped_column(default=list)
    in_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    in_errors: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_errors: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    in_discards: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    out_discards: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_counters: Mapped[dict] = mapped_column(default=dict)  # raw counters + ts for rate calculation
    status_changed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    flap_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("switch_id", "if_index", name="uq_switch_ports_ifindex"),
        UniqueConstraint("switch_id", "name", name="uq_switch_ports_name"),
    )


class SwitchNeighbor(Base):
    __tablename__ = "switch_neighbors"
    id: Mapped[int] = mapped_column(primary_key=True)
    switch_id: Mapped[int] = mapped_column(ForeignKey("switches.id", ondelete="CASCADE"), index=True)
    local_port: Mapped[str] = mapped_column(String(32))
    chassis_id: Mapped[str] = mapped_column(String(64), default="")
    remote_port: Mapped[str] = mapped_column(String(64), default="")
    remote_port_desc: Mapped[str] = mapped_column(String(255), default="")
    system_name: Mapped[str] = mapped_column(String(255), default="")
    system_description: Mapped[str] = mapped_column(Text, default="")
    mgmt_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capabilities: Mapped[list] = mapped_column(default=list)
    remote_switch_id: Mapped[int | None] = mapped_column(ForeignKey("switches.id", ondelete="SET NULL"),
                                                         nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="lldp")  # lldp | manual
    first_seen: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(default=utcnow)

    __table_args__ = (
        UniqueConstraint("switch_id", "local_port", "chassis_id", "remote_port", "source",
                         name="uq_switch_neighbors_link"),
    )


__all__ = ["Site", "SwitchModel", "SwitchGroup", "SwitchGroupMember", "Switch", "SwitchCredential", "SwitchPort",
           "SwitchNeighbor", "Index"]
