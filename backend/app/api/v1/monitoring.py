"""Dashboard, time-series metrics, connected devices, PoE overview and reports."""

from __future__ import annotations

import csv
import io
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import not_found
from app.core.permissions import P
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    Alert,
    AuditLog,
    ChangeJob,
    MacLearnedEntry,
    PoeConfiguration,
    Switch,
    SwitchEvent,
    SwitchNeighbor,
    SwitchPort,
    User,
)
from app.services import audit
from app.services import settings as sysset

router = APIRouter(tags=["monitoring"])

RANGES = {"1h": (timedelta(hours=1), "1 minute"), "6h": (timedelta(hours=6), "5 minutes"),
          "24h": (timedelta(hours=24), "15 minutes"), "7d": (timedelta(days=7), "2 hours"),
          "30d": (timedelta(days=30), "6 hours")}
RangeT = Literal["1h", "6h", "24h", "7d", "30d"]


@router.get("/dashboard/overview")
def overview(user: User = Depends(require(P.DASHBOARD_VIEW)), db: Session = Depends(get_db)) -> dict:
    stale_after = int(sysset.get(db, "metrics.stale_after_seconds"))
    now = utcnow()
    switches = db.execute(select(Switch)).unique().scalars().all()
    status_counts = {"online": 0, "offline": 0, "warning": 0, "unknown": 0}
    for s in switches:
        status_counts[s.status if s.status in status_counts else "unknown"] += 1
    ports = db.execute(select(func.count(), func.count().filter(SwitchPort.oper_up.is_(True)),
                              func.count().filter(SwitchPort.admin_up.is_(False)),
                              func.count().filter(or_(SwitchPort.in_errors > 0, SwitchPort.out_errors > 0)))).one()
    fresh = [s for s in switches if s.metrics_at and (now - s.metrics_at).total_seconds() <= stale_after]
    poe_rows = [s for s in switches if s.poe_budget_w is not None and s.last_success_at and
                (now - s.last_success_at).total_seconds() <= stale_after * 2]
    poe_budget = sum(s.poe_budget_w or 0 for s in poe_rows)
    poe_used = sum(s.poe_consumed_w or 0 for s in poe_rows)
    # Current aggregate traffic: sum of latest per-port rates on access ports that are fresh.
    traffic = db.execute(select(func.sum(SwitchPort.in_bps), func.sum(SwitchPort.out_bps), func.max(SwitchPort.updated_at))
                         .where(SwitchPort.is_uplink.is_(False), SwitchPort.in_bps.is_not(None),
                                SwitchPort.updated_at >= now - timedelta(seconds=stale_after))).one()
    devices = db.execute(select(func.count(func.distinct(MacLearnedEntry.mac))).where(MacLearnedEntry.active.is_(True))).scalar_one()
    top_switches = db.execute(text("""
        SELECT s.id, s.hostname, s.is_simulated, sum(p.in_bps) AS in_bps, sum(p.out_bps) AS out_bps
        FROM switch_ports p JOIN switches s ON s.id = p.switch_id
        WHERE p.in_bps IS NOT NULL AND p.is_uplink = false AND p.updated_at >= :since
        GROUP BY s.id ORDER BY coalesce(sum(p.in_bps),0) + coalesce(sum(p.out_bps),0) DESC LIMIT 5"""),
        {"since": now - timedelta(seconds=stale_after)}).mappings().all()
    top_ports = db.execute(text("""
        SELECT s.id AS switch_id, s.hostname, s.is_simulated, p.name AS port, p.description, p.in_bps, p.out_bps,
               p.speed_mbps
        FROM switch_ports p JOIN switches s ON s.id = p.switch_id
        WHERE p.in_bps IS NOT NULL AND p.updated_at >= :since
        ORDER BY coalesce(p.in_bps,0) + coalesce(p.out_bps,0) DESC LIMIT 10"""),
        {"since": now - timedelta(seconds=stale_after)}).mappings().all()
    events = db.execute(select(SwitchEvent, Switch.hostname).outerjoin(Switch, Switch.id == SwitchEvent.switch_id)
                        .order_by(SwitchEvent.ts.desc()).limit(15)).all()
    changes = db.execute(select(ChangeJob).order_by(ChangeJob.created_at.desc()).limit(10)).scalars().all()
    active_alerts = db.execute(select(Alert.severity, func.count()).where(Alert.status != "resolved")
                               .group_by(Alert.severity)).all()
    health = [{"id": s.id, "hostname": s.hostname, "status": s.status, "is_simulated": s.is_simulated,
               "cpu_pct": s.cpu_pct, "mem_pct": s.mem_pct, "temperature_c": s.temperature_c,
               "uptime_seconds": s.uptime_seconds, "metrics_at": s.metrics_at,
               "stale": s not in fresh} for s in sorted(switches, key=lambda x: -(x.cpu_pct or 0))[:12]]
    return {
        "generated_at": now, "stale_after_seconds": stale_after,
        "switches": {"total": len(switches), **status_counts, "simulated": sum(1 for s in switches if s.is_simulated),
                     "with_fresh_metrics": len(fresh)},
        "ports": {"total": ports[0], "up": ports[1], "down": ports[0] - ports[1], "admin_down": ports[2],
                  "with_errors": ports[3]},
        "traffic": {"in_bps": traffic[0], "out_bps": traffic[1], "at": traffic[2],
                    "available": traffic[0] is not None},
        "poe": {"budget_w": poe_budget if poe_rows else None, "consumed_w": poe_used if poe_rows else None,
                "available_w": (poe_budget - poe_used) if poe_rows else None, "switches_reporting": len(poe_rows)},
        "devices": {"connected": devices},
        "alerts": {sev: n for sev, n in active_alerts},
        "top_switches": [dict(r) for r in top_switches],
        "top_ports": [dict(r) for r in top_ports],
        "health": health,
        "recent_events": [{"id": e.id, "ts": e.ts, "severity": e.severity, "type": e.type, "message": e.message,
                           "switch_id": e.switch_id, "hostname": h, "port_name": e.port_name} for e, h in events],
        "recent_changes": [{"id": j.id, "title": j.title, "status": j.status, "risk": j.risk,
                            "requested_by": j.requested_by_name, "created_at": j.created_at} for j in changes],
    }


def _bucketed(db: Session, table: str, cols: str, where: str, params: dict, rng: str) -> list[dict]:
    span, bucket = RANGES[rng]
    params = {**params, "since": utcnow() - span}
    q = text(f"""SELECT date_bin(INTERVAL '{bucket}', ts, TIMESTAMPTZ '2000-01-01') AS t, {cols}
                 FROM {table} WHERE ts >= :since AND {where} GROUP BY 1 ORDER BY 1""")  # noqa: S608 - fixed fragments
    return [dict(r) for r in db.execute(q, params).mappings().all()]


@router.get("/metrics/traffic")
def fleet_traffic(range: RangeT = "24h", user: User = Depends(require(P.METRICS_VIEW)),  # noqa: A002
                  db: Session = Depends(get_db)) -> dict:
    # Per bucket: average per switch, then summed across switches.
    span, bucket = RANGES[range]
    q = text(f"""
      SELECT t, sum(in_bps) AS in_bps, sum(out_bps) AS out_bps FROM (
        SELECT date_bin(INTERVAL '{bucket}', ts, TIMESTAMPTZ '2000-01-01') AS t, switch_id,
               avg(in_bps) AS in_bps, avg(out_bps) AS out_bps
        FROM switch_metrics WHERE ts >= :since AND in_bps IS NOT NULL GROUP BY 1, 2) x
      GROUP BY t ORDER BY t""")  # noqa: S608
    rows = db.execute(q, {"since": utcnow() - span}).mappings().all()
    return {"range": range, "bucket": bucket, "points": [dict(r) for r in rows]}


@router.get("/metrics/switches/{switch_id}")
def switch_metrics(switch_id: int, range: RangeT = "24h", user: User = Depends(require(P.METRICS_VIEW)),  # noqa: A002
                   db: Session = Depends(get_db)) -> dict:
    if db.get(Switch, switch_id) is None:
        raise not_found("Switch")
    pts = _bucketed(db, "switch_metrics",
                    "avg(cpu_pct) AS cpu_pct, avg(mem_pct) AS mem_pct, avg(temperature_c) AS temperature_c, "
                    "avg(in_bps) AS in_bps, avg(out_bps) AS out_bps, avg(poe_consumed_w) AS poe_consumed_w, "
                    "max(poe_budget_w) AS poe_budget_w, avg(latency_ms) AS latency_ms, "
                    "bool_and(reachable) AS reachable, count(*) FILTER (WHERE NOT reachable) AS failures",
                    "switch_id = :sid", {"sid": switch_id}, range)
    return {"range": range, "bucket": RANGES[range][1], "points": pts}


@router.get("/metrics/switches/{switch_id}/ports/{if_index}")
def port_metrics(switch_id: int, if_index: int, range: RangeT = "24h", user: User = Depends(require(P.METRICS_VIEW)),  # noqa: A002
                 db: Session = Depends(get_db)) -> dict:
    pts = _bucketed(db, "port_metrics",
                    "avg(in_bps) AS in_bps, avg(out_bps) AS out_bps, max(in_errors) - min(in_errors) AS in_errors, "
                    "max(out_errors) - min(out_errors) AS out_errors, max(in_discards) - min(in_discards) AS in_discards, "
                    "bool_or(oper_up) AS oper_up",
                    "switch_id = :sid AND if_index = :idx", {"sid": switch_id, "idx": if_index}, range)
    return {"range": range, "bucket": RANGES[range][1], "points": pts}


@router.get("/metrics/switches/{switch_id}/poe")
def poe_metrics(switch_id: int, range: RangeT = "24h", port: str | None = None,  # noqa: A002
                user: User = Depends(require(P.POE_VIEW)), db: Session = Depends(get_db)) -> dict:
    where = "switch_id = :sid" + (" AND port_name = :port" if port else "")
    params: dict = {"sid": switch_id}
    if port:
        params["port"] = port
    span, bucket = RANGES[range]
    q = text(f"""SELECT t, sum(power_w) AS power_w FROM (
                 SELECT date_bin(INTERVAL '{bucket}', ts, TIMESTAMPTZ '2000-01-01') AS t, port_name, avg(power_w) AS power_w
                 FROM poe_metrics WHERE ts >= :since AND {where} GROUP BY 1, 2) x GROUP BY t ORDER BY t""")  # noqa: S608
    rows = db.execute(q, {**params, "since": utcnow() - span}).mappings().all()
    return {"range": range, "bucket": bucket, "points": [dict(r) for r in rows]}


@router.get("/poe/overview")
def poe_overview(user: User = Depends(require(P.POE_VIEW)), db: Session = Depends(get_db)) -> dict:
    switches = db.execute(select(Switch).order_by(Switch.hostname)).unique().scalars().all()
    stats = db.execute(select(PoeConfiguration.switch_id,
                              func.count().filter(PoeConfiguration.detection_status == "delivering"),
                              func.count().filter(PoeConfiguration.detection_status == "fault"),
                              func.count().filter(PoeConfiguration.enabled.is_(False)))
                       .group_by(PoeConfiguration.switch_id)).all()
    by = {r[0]: r[1:] for r in stats}
    faults = db.execute(select(PoeConfiguration, Switch.hostname).join(Switch, Switch.id == PoeConfiguration.switch_id)
                        .where(PoeConfiguration.detection_status == "fault")).all()
    top = db.execute(select(PoeConfiguration, Switch.hostname).join(Switch, Switch.id == PoeConfiguration.switch_id)
                     .where(PoeConfiguration.power_drawn_w.is_not(None))
                     .order_by(PoeConfiguration.power_drawn_w.desc()).limit(10)).all()
    rows = []
    for s in switches:
        d, f, off = by.get(s.id, (0, 0, 0))
        rows.append({"switch_id": s.id, "hostname": s.hostname, "is_simulated": s.is_simulated, "status": s.status,
                     "budget_w": s.poe_budget_w, "consumed_w": s.poe_consumed_w, "metrics_at": s.metrics_at,
                     "pct": round(100 * s.poe_consumed_w / s.poe_budget_w, 1) if s.poe_budget_w and s.poe_consumed_w is not None else None,
                     "delivering": d, "faults": f, "disabled": off})
    total_b = sum(r["budget_w"] or 0 for r in rows if r["budget_w"] is not None)
    total_c = sum(r["consumed_w"] or 0 for r in rows if r["consumed_w"] is not None)
    reporting = [r for r in rows if r["budget_w"] is not None]
    return {"budget_w": total_b if reporting else None, "consumed_w": total_c if reporting else None,
            "available_w": total_b - total_c if reporting else None, "switches_reporting": len(reporting),
            "switches": rows,
            "faults": [{"switch_id": p.switch_id, "hostname": h, "port": p.port_name, "fault": p.fault} for p, h in faults],
            "top_ports": [{"switch_id": p.switch_id, "hostname": h, "port": p.port_name, "power_w": p.power_drawn_w,
                           "power_class": p.power_class} for p, h in top]}


@router.get("/devices")
def devices(q: str | None = None, switch_id: int | None = None, vlan_id: int | None = None,
            active: bool | None = True, page: int = Query(1, ge=1), page_size: int = Query(100, le=500),
            user: User = Depends(require(P.DEVICE_VIEW)), db: Session = Depends(get_db)) -> dict:
    stmt = select(MacLearnedEntry, Switch.hostname, Switch.is_simulated).join(Switch, Switch.id == MacLearnedEntry.switch_id)
    if q:
        norm = q.lower().replace("-", ":").replace(".", "")
        like = f"%{norm}%"
        stmt = stmt.where(or_(MacLearnedEntry.mac.like(like), func.lower(MacLearnedEntry.vendor).like(f"%{q.lower()}%"),
                              func.lower(Switch.hostname).like(f"%{q.lower()}%")))
    if switch_id:
        stmt = stmt.where(MacLearnedEntry.switch_id == switch_id)
    if vlan_id:
        stmt = stmt.where(MacLearnedEntry.vlan_id == vlan_id)
    if active is not None:
        stmt = stmt.where(MacLearnedEntry.active.is_(active))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(MacLearnedEntry.last_seen.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    nb = {(n.switch_id, n.local_port): n for n in db.execute(select(SwitchNeighbor)).scalars()}
    items = []
    for m, host, sim in rows:
        n = nb.get((m.switch_id, m.port_name))
        items.append({"mac": m.mac, "vlan_id": m.vlan_id, "switch_id": m.switch_id, "hostname": host,
                      "is_simulated": sim, "port": m.port_name, "vendor": m.vendor, "first_seen": m.first_seen,
                      "last_seen": m.last_seen, "active": m.active,
                      "lldp": {"system_name": n.system_name, "remote_port": n.remote_port} if n else None})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# ------------------------------------------------------------------ reports

def _period(period: str) -> timedelta:
    return {"daily": timedelta(days=1), "weekly": timedelta(days=7), "monthly": timedelta(days=30)}[period]


def _report(db: Session, kind: str, period: str) -> tuple[list[str], list[list]]:
    since = utcnow() - _period(period)
    if kind == "availability":
        rows = db.execute(text("""
            SELECT s.id, s.hostname, s.mgmt_ip, s.is_simulated, count(m.ts) AS samples,
                   count(m.ts) FILTER (WHERE m.reachable) AS up_samples
            FROM switches s LEFT JOIN switch_metrics m ON m.switch_id = s.id AND m.ts >= :since
              AND (m.latency_ms IS NOT NULL OR NOT m.reachable)
            GROUP BY s.id ORDER BY s.hostname"""), {"since": since}).mappings().all()
        header = ["switch_id", "hostname", "mgmt_ip", "simulated", "samples", "availability_pct"]
        data = [[r["id"], r["hostname"], r["mgmt_ip"], r["is_simulated"], r["samples"],
                 round(100 * r["up_samples"] / r["samples"], 2) if r["samples"] else None] for r in rows]
        return header, data
    if kind == "bandwidth":
        rows = db.execute(text("""
            SELECT s.id, s.hostname, s.is_simulated, avg(m.in_bps) AS avg_in, avg(m.out_bps) AS avg_out,
                   max(m.in_bps) AS peak_in, max(m.out_bps) AS peak_out
            FROM switches s JOIN switch_metrics m ON m.switch_id = s.id
            WHERE m.ts >= :since AND m.in_bps IS NOT NULL GROUP BY s.id
            ORDER BY avg(m.in_bps) + avg(m.out_bps) DESC"""), {"since": since}).mappings().all()
        header = ["switch_id", "hostname", "simulated", "avg_in_bps", "avg_out_bps", "peak_in_bps", "peak_out_bps"]
        return header, [[r["id"], r["hostname"], r["is_simulated"], r["avg_in"], r["avg_out"], r["peak_in"],
                         r["peak_out"]] for r in rows]
    if kind == "ports":
        rows = db.execute(text("""
            SELECT s.hostname, s.is_simulated, p.name, p.description, p.speed_mbps,
                   avg(m.in_bps) AS avg_in, avg(m.out_bps) AS avg_out, max(m.in_bps) AS peak_in,
                   max(m.out_bps) AS peak_out,
                   max(m.in_errors) - min(m.in_errors) AS in_errors
            FROM port_metrics m JOIN switch_ports p ON p.switch_id = m.switch_id AND p.if_index = m.if_index
            JOIN switches s ON s.id = m.switch_id
            WHERE m.ts >= :since GROUP BY s.hostname, s.is_simulated, p.name, p.description, p.speed_mbps
            ORDER BY coalesce(avg(m.in_bps),0) + coalesce(avg(m.out_bps),0) DESC LIMIT 500"""),
            {"since": since}).mappings().all()
        header = ["hostname", "simulated", "port", "description", "speed_mbps", "avg_in_bps", "avg_out_bps",
                  "peak_in_bps", "peak_out_bps", "utilisation_pct", "in_errors"]
        data = []
        for r in rows:
            util = None
            if r["speed_mbps"] and r["peak_in"] is not None:
                util = round(100 * max(r["peak_in"] or 0, r["peak_out"] or 0) / (r["speed_mbps"] * 1e6), 2)
            data.append([r["hostname"], r["is_simulated"], r["name"], r["description"], r["speed_mbps"], r["avg_in"],
                         r["avg_out"], r["peak_in"], r["peak_out"], util, r["in_errors"]])
        return header, data
    raise not_found("Report")


@router.get("/reports/{kind}")
def report(kind: Literal["availability", "bandwidth", "ports"], period: Literal["daily", "weekly", "monthly"] = "daily",
           user: User = Depends(require(P.REPORT_VIEW)), db: Session = Depends(get_db)) -> dict:
    header, data = _report(db, kind, period)
    return {"kind": kind, "period": period, "generated_at": utcnow(), "columns": header,
            "rows": [dict(zip(header, r, strict=True)) for r in data]}


@router.get("/reports/{kind}/export")
def export_report(kind: Literal["availability", "bandwidth", "ports"],
                  period: Literal["daily", "weekly", "monthly"] = "daily",
                  user: User = Depends(require(P.REPORT_EXPORT)), db: Session = Depends(get_db)) -> StreamingResponse:
    header, data = _report(db, kind, period)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in data:
        w.writerow(["" if v is None else v for v in r])
    audit.record(db, action="report.export", actor=user, details={"kind": kind, "period": period, "rows": len(data)})
    db.commit()
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="anm-{kind}-{period}.csv"'})


@router.get("/search")
def global_search(q: str = Query(min_length=2, max_length=64), user: User = Depends(require(P.SWITCH_VIEW)),
                  db: Session = Depends(get_db)) -> dict:
    from app.core.permissions import has_permission

    like = f"%{q.lower()}%"
    sws = db.execute(select(Switch).where(or_(func.lower(Switch.hostname).like(like), Switch.mgmt_ip.like(like),
                                              func.lower(Switch.serial_number).like(like),
                                              func.lower(Switch.location).like(like))).limit(10)).unique().scalars().all()
    ports = db.execute(select(SwitchPort, Switch.hostname).join(Switch, Switch.id == SwitchPort.switch_id)
                       .where(func.lower(SwitchPort.description).like(like)).limit(10)).all()
    macs = []
    if has_permission(user.role, P.DEVICE_VIEW):
        norm = f"%{q.lower().replace('-', ':')}%"
        macs = db.execute(select(MacLearnedEntry, Switch.hostname).join(Switch, Switch.id == MacLearnedEntry.switch_id)
                          .where(and_(MacLearnedEntry.mac.like(norm), MacLearnedEntry.active.is_(True))).limit(10)).all()
    return {"switches": [{"id": s.id, "hostname": s.hostname, "mgmt_ip": s.mgmt_ip, "status": s.status} for s in sws],
            "ports": [{"switch_id": p.switch_id, "hostname": h, "port": p.name, "description": p.description}
                      for p, h in ports],
            "devices": [{"switch_id": m.switch_id, "hostname": h, "port": m.port_name, "mac": m.mac, "vlan_id": m.vlan_id}
                        for m, h in macs]}


__all__ = ["router", "AuditLog"]
