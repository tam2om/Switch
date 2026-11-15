from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.errors import bad_request, not_found
from app.core.permissions import P
from app.db.session import get_db
from app.drivers.aruba.aos_switch import cli_commands as cli
from app.models import Switch, SwitchNeighbor, SwitchPort, User
from app.services import audit

router = APIRouter(prefix="/topology", tags=["topology"])


class ManualLinkIn(BaseModel):
    switch_id: int
    local_port: str
    remote_switch_id: int | None = None
    remote_name: str = Field(default="", max_length=255)
    remote_port: str = Field(default="", max_length=64)

    @field_validator("local_port")
    @classmethod
    def _p(cls, v: str) -> str:
        return cli.port(v)


@router.get("")
def topology(include_devices: bool = False, user: User = Depends(require(P.TOPOLOGY_VIEW)),
             db: Session = Depends(get_db)) -> dict:
    switches = db.execute(select(Switch)).unique().scalars().all()
    nodes = [{"id": f"s{s.id}", "switch_id": s.id, "label": s.hostname, "kind": "switch", "status": s.status,
              "is_simulated": s.is_simulated, "mgmt_ip": s.mgmt_ip, "building": s.building} for s in switches]
    ports = {(p.switch_id, p.name): p for p in db.execute(select(SwitchPort)).scalars()}
    edges = []
    seen = set()
    ext_nodes: dict[str, dict] = {}
    for n in db.execute(select(SwitchNeighbor)).scalars():
        lp = ports.get((n.switch_id, n.local_port))
        link_up = lp.oper_up if lp else None
        vlans = {"untagged": lp.untagged_vlan, "tagged": lp.tagged_vlans} if lp else None
        if n.remote_switch_id:
            key = tuple(sorted([(n.switch_id, n.local_port), (n.remote_switch_id, n.remote_port)]))
            if key in seen:
                continue
            seen.add(key)
            edges.append({"id": f"e{n.id}", "source": f"s{n.switch_id}", "target": f"s{n.remote_switch_id}",
                          "source_port": n.local_port, "target_port": n.remote_port, "kind": "uplink",
                          "source_type": n.source, "link_up": link_up, "vlans": vlans})
        elif include_devices:
            nid = f"d{n.chassis_id or n.system_name}"
            ext_nodes.setdefault(nid, {"id": nid, "label": n.system_name or n.chassis_id, "kind": "device",
                                       "description": n.system_description[:120]})
            edges.append({"id": f"e{n.id}", "source": f"s{n.switch_id}", "target": nid, "source_port": n.local_port,
                          "target_port": n.remote_port, "kind": "device", "source_type": n.source, "link_up": link_up,
                          "vlans": vlans})
    return {"nodes": nodes + list(ext_nodes.values()), "edges": edges}


@router.post("/links", status_code=201)
def add_link(body: ManualLinkIn, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    if db.get(Switch, body.switch_id) is None:
        raise not_found("Switch")
    if body.remote_switch_id is None and not body.remote_name:
        raise bad_request("Specify a remote switch or a remote device name")
    remote = db.get(Switch, body.remote_switch_id) if body.remote_switch_id else None
    if body.remote_switch_id and remote is None:
        raise not_found("Remote switch")
    n = SwitchNeighbor(switch_id=body.switch_id, local_port=body.local_port, remote_switch_id=body.remote_switch_id,
                       system_name=remote.hostname if remote else body.remote_name, remote_port=body.remote_port,
                       chassis_id=f"manual-{body.remote_switch_id or body.remote_name}", source="manual")
    db.add(n)
    db.flush()
    audit.record(db, action="topology.link_add", actor=user, target_type="link", target_id=n.id,
                 switch_id=body.switch_id, details=body.model_dump())
    db.commit()
    return {"id": n.id}


@router.delete("/links/{link_id}")
def delete_link(link_id: int, user: User = Depends(require(P.SWITCH_MANAGE)), db: Session = Depends(get_db)) -> dict:
    n = db.get(SwitchNeighbor, link_id)
    if n is None or n.source != "manual":
        raise not_found("Manual link")
    audit.record(db, action="topology.link_delete", actor=user, target_type="link", target_id=n.id, switch_id=n.switch_id)
    db.delete(n)
    db.commit()
    return {"ok": True}
