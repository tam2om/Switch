"""Optional integrations. The application works fully without them; they only import inventory, link records
and surface external status."""

from __future__ import annotations

import ipaddress

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import get_keyring
from app.db.base import utcnow
from app.integrations.airwave import AirWaveClient
from app.integrations.zabbix import IntegrationError, ZabbixClient
from app.models import IntegrationSetting, Switch

KINDS = ("zabbix", "airwave")


def get_or_create(db: Session, kind: str) -> IntegrationSetting:
    row = db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == kind)).scalar_one_or_none()
    if row is None:
        row = IntegrationSetting(kind=kind)
        db.add(row)
        db.flush()
    return row


def secret(row: IntegrationSetting) -> str:
    return get_keyring().decrypt_str(row.secret_enc, f"integration:{row.kind}") if row.secret_enc else ""


def set_secret(row: IntegrationSetting, value: str) -> None:
    row.secret_enc = get_keyring().encrypt_str(value, f"integration:{row.kind}")


def public(row: IntegrationSetting) -> dict:
    return {"kind": row.kind, "enabled": row.enabled, "url": row.url, "username": row.username,
            "has_secret": bool(row.secret_enc), "verify_tls": row.verify_tls, "params": row.params,
            "last_sync_at": row.last_sync_at, "last_status": row.last_status, "last_message": row.last_message}


def client(row: IntegrationSetting, transport=None):  # type: ignore[no-untyped-def]
    if row.kind == "zabbix":
        return ZabbixClient(row.url, secret(row), verify=row.verify_tls, transport=transport)
    return AirWaveClient(row.url, row.username, secret(row), verify=row.verify_tls, transport=transport)


def test(db: Session, kind: str, transport=None) -> dict:  # type: ignore[no-untyped-def]
    row = get_or_create(db, kind)
    if not row.url:
        raise IntegrationError("URL is not configured")
    c = client(row, transport)
    try:
        if kind == "zabbix":
            return {"ok": True, "version": c.version(), "hosts": len(c.hosts(row.params.get("host_group")))}
        devs = c.devices()
        return {"ok": True, "devices": len(devs), "switches": len([d for d in devs if _is_switch(d)])}
    finally:
        c.close()


def _is_switch(d: dict) -> bool:
    model = d.get("model", "")
    return d.get("device_category", "").lower() == "switch" or "switch" in model.lower() or \
        any(f in model for f in ("2540", "2930", "5406", "5412"))


def preview(db: Session, kind: str, transport=None) -> list[dict]:  # type: ignore[no-untyped-def]
    row = get_or_create(db, kind)
    c = client(row, transport)
    by_ip = {s.mgmt_ip: s for s in db.execute(select(Switch)).unique().scalars()}
    out = []
    try:
        if kind == "zabbix":
            for h in c.hosts(row.params.get("host_group")):
                ip = next((i["ip"] for i in h.get("interfaces", []) if i.get("main") == "1"), None) or \
                    next((i["ip"] for i in h.get("interfaces", [])), None)
                existing = by_ip.get(ip or "")
                out.append({"external_id": h["hostid"], "name": h.get("host"), "ip": ip,
                            "model": (h.get("inventory") or {}).get("model") if isinstance(h.get("inventory"), dict) else None,
                            "matched_switch_id": existing.id if existing else None, "url": c.host_url(h["hostid"])})
        else:
            for d in c.devices():
                if not _is_switch(d):
                    continue
                existing = by_ip.get(d["ip"])
                out.append({"external_id": d["id"], "name": d["name"], "ip": d["ip"], "model": d["model"],
                            "matched_switch_id": existing.id if existing else None, "url": c.device_url(d["id"])})
    finally:
        c.close()
    return out


def sync(db: Session, kind: str, import_new: bool = False, transport=None) -> dict:  # type: ignore[no-untyped-def]
    """Link existing switches by management IP; optionally import new ones (as unverified inventory)."""
    row = get_or_create(db, kind)
    if not row.enabled:
        return {"skipped": "integration disabled"}
    try:
        items = preview(db, kind, transport)
        linked = imported = 0
        for it in items:
            sw = db.get(Switch, it["matched_switch_id"]) if it["matched_switch_id"] else None
            if sw is None and import_new and it["ip"]:
                try:
                    ipaddress.ip_address(it["ip"])
                except ValueError:
                    continue
                name = "".join(ch for ch in (it["name"] or it["ip"]) if ch.isalnum() or ch in "-_.")[:128] or it["ip"]
                sw = Switch(hostname=name, mgmt_ip=it["ip"], status="unknown",
                            notes=f"Imported from {kind}; verify credentials and identity before use")
                db.add(sw)
                db.flush()
                imported += 1
            if sw is not None:
                ext = dict(sw.external_ids or {})
                ext[kind] = {"id": it["external_id"], "url": it["url"]}
                sw.external_ids = ext
                linked += 1
        problems = 0
        if kind == "zabbix":
            c = client(row, transport)
            try:
                hostmap = {v["id"]: s.id for s in db.execute(select(Switch)).unique().scalars()
                           for k, v in (s.external_ids or {}).items() if k == "zabbix"}
                probs = c.problems(list(hostmap))
                per: dict[int, list[dict]] = {}
                for p in probs:
                    for h in p.get("hosts", []):
                        sid = hostmap.get(h["hostid"])
                        if sid:
                            per.setdefault(sid, []).append({"name": p["name"], "severity": int(p.get("severity", 0)),
                                                            "clock": p.get("clock")})
                for sw in db.execute(select(Switch)).unique().scalars():
                    if "zabbix" in (sw.external_ids or {}):
                        ext = dict(sw.external_ids)
                        ext["zabbix"] = {**ext["zabbix"], "problems": per.get(sw.id, [])[:20], "synced_at": utcnow().isoformat()}
                        sw.external_ids = ext
                problems = len(probs)
            finally:
                c.close()
        row.last_sync_at = utcnow()
        row.last_status = "ok"
        row.last_message = f"{linked} linked, {imported} imported" + (f", {problems} problems" if kind == "zabbix" else "")
        return {"linked": linked, "imported": imported, "problems": problems, "seen": len(items)}
    except IntegrationError as exc:
        row.last_sync_at = utcnow()
        row.last_status = "failed"
        row.last_message = str(exc)[:500]
        return {"error": str(exc)}
