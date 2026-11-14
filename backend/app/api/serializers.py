"""Response shaping. Measurements carry their timestamp and a 'stale' flag; missing values stay null."""

from __future__ import annotations

from datetime import datetime

from app.db.base import utcnow
from app.models import Switch, SwitchPort


def _age(ts: datetime | None) -> float | None:
    return (utcnow() - ts).total_seconds() if ts else None


def switch_out(sw: Switch, stale_after: int = 180, groups: list[dict] | None = None) -> dict:
    age = _age(sw.metrics_at)
    poll_age = _age(sw.last_success_at)
    return {
        "id": sw.id, "hostname": sw.hostname, "mgmt_ip": sw.mgmt_ip, "status": sw.status,
        "status_reason": sw.status_reason, "is_simulated": sw.is_simulated, "driver": sw.driver,
        "product_number": sw.product_number, "model_name": sw.model_name or (sw.model.name if sw.model else None),
        "model_verified": bool(sw.model and sw.model.hardware_verified),
        "serial_number": sw.serial_number, "base_mac": sw.base_mac, "firmware": sw.firmware,
        "rom_version": sw.rom_version, "site_id": sw.site_id, "site": sw.site.name if sw.site else None,
        "location": sw.location, "building": sw.building, "floor": sw.floor, "department": sw.department,
        "mgmt_vlan": sw.mgmt_vlan, "uplink_ports": sw.uplink_ports or [], "monitoring_enabled": sw.monitoring_enabled,
        "protocols": sw.protocols, "rest_api_version": sw.rest_api_version,
        "last_poll_at": sw.last_poll_at, "last_success_at": sw.last_success_at,
        "poll_stale": poll_age is None or poll_age > stale_after,
        "metrics": {
            "at": sw.metrics_at, "stale": age is None or age > stale_after,
            "uptime_seconds": sw.uptime_seconds, "cpu_pct": sw.cpu_pct, "mem_pct": sw.mem_pct,
            "temperature_c": sw.temperature_c, "poe_budget_w": sw.poe_budget_w, "poe_consumed_w": sw.poe_consumed_w,
        },
        "capabilities": sw.capabilities or {},
        "ssh_host_key_fingerprint": sw.ssh_host_key_fingerprint, "ssh_host_key_trusted": sw.ssh_host_key_trusted,
        "notes": sw.notes, "external_ids": sw.external_ids or {}, "groups": groups or [],
        "created_at": sw.created_at, "updated_at": sw.updated_at,
    }


def port_out(p: SwitchPort, poe: dict | None = None, macs: list[dict] | None = None,
             neighbors: list[dict] | None = None) -> dict:
    return {
        "id": p.id, "name": p.name, "if_index": p.if_index, "port_number": p.port_number,
        "description": p.description, "port_type": p.port_type, "is_uplink": p.is_uplink,
        "trunk_group": p.trunk_group, "admin_up": p.admin_up, "oper_up": p.oper_up, "speed_mbps": p.speed_mbps,
        "duplex": p.duplex, "config_mode": p.config_mode, "untagged_vlan": p.untagged_vlan,
        "tagged_vlans": p.tagged_vlans or [], "in_bps": p.in_bps, "out_bps": p.out_bps, "in_errors": p.in_errors,
        "out_errors": p.out_errors, "in_discards": p.in_discards, "out_discards": p.out_discards,
        "flap_count": p.flap_count, "status_changed_at": p.status_changed_at, "updated_at": p.updated_at,
        "poe": poe, "macs": macs or [], "neighbors": neighbors or [],
    }
