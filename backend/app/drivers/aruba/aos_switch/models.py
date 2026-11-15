"""Catalogue of AOS-Switch hardware models the application knows how to lay out.

Port counts, uplink types and PoE budgets follow the published HPE/Aruba product specifications. None of these
models has been validated on physical hardware by this project (see docs/HARDWARE_COMPATIBILITY.md).

Two port-naming schemes exist on AOS-Switch:
* fixed-port switches (2540, 2930F): ports are numbered 1..N, uplinks follow the access ports;
* modular chassis (5400R zl2): ports are named <slot letter><number>, e.g. A1, B24. What a slot holds depends on
  the installed module, so the port type of a slot port is not assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# AOS-Switch numbers modular ports per slot with a stride of 24 ifIndex values (A1=1, B1=25, ...). SNMP IF-MIB
# provides the real ifIndex and always takes precedence; this is only used when a port is first seen over REST.
SLOT_IFINDEX_STRIDE = 24

_SLOT_PORT = re.compile(r"^([A-L])(\d{1,2})$")


@dataclass(frozen=True)
class ModelSpec:
    product_number: str
    name: str
    family: str
    access_ports: int  # fixed copper ports; 0 on a modular chassis
    uplink_ports: int  # fixed uplink ports after the access ports; 0 on a modular chassis
    uplink_type: str = "SFP+"  # SFP+ | SFP
    poe: bool = False
    poe_budget_w: float | None = None  # None: not PoE, or budget depends on power supplies (read from the device)
    modular: bool = False
    slots: str = ""  # slot letters on a modular chassis

    def port_layout(self) -> dict:
        if self.modular:
            return {"modular": True, "slots": list(self.slots)}
        first = self.access_ports + 1
        return {"rows": 2, "access": self.access_ports,
                "uplinks": list(range(first, first + self.uplink_ports)), "uplink_type": self.uplink_type}


def _m(pn: str, name: str, family: str, access: int, uplinks: int, uplink_type: str = "SFP+",
       poe_w: float | None = None, *, modular: bool = False, slots: str = "") -> ModelSpec:
    return ModelSpec(pn, name, family, access, uplinks, uplink_type, poe=poe_w is not None,
                     poe_budget_w=poe_w, modular=modular, slots=slots)


MODELS: dict[str, ModelSpec] = {m.product_number: m for m in [
    # Aruba 2540 (firmware YC.16.x)
    _m("JL356A", "Aruba 2540 24G PoE+ 4SFP+ Switch", "2540", 24, 4, "SFP+", 370.0),
    _m("JL354A", "Aruba 2540 24G 4SFP+ Switch", "2540", 24, 4, "SFP+"),
    _m("JL357A", "Aruba 2540 48G PoE+ 4SFP+ Switch", "2540", 48, 4, "SFP+", 370.0),
    _m("JL355A", "Aruba 2540 48G 4SFP+ Switch", "2540", 48, 4, "SFP+"),
    # Aruba 2930F (firmware WC.16.x)
    _m("JL258A", "Aruba 2930F 8G PoE+ 2SFP+ Switch", "2930F", 8, 2, "SFP+", 125.0),
    _m("JL253A", "Aruba 2930F 24G 4SFP Switch", "2930F", 24, 4, "SFP"),
    _m("JL254A", "Aruba 2930F 48G 4SFP Switch", "2930F", 48, 4, "SFP"),
    _m("JL255A", "Aruba 2930F 24G PoE+ 4SFP Switch", "2930F", 24, 4, "SFP", 370.0),
    _m("JL256A", "Aruba 2930F 48G PoE+ 4SFP Switch", "2930F", 48, 4, "SFP", 370.0),
    _m("JL259A", "Aruba 2930F 24G 4SFP+ Switch", "2930F", 24, 4, "SFP+"),
    _m("JL260A", "Aruba 2930F 48G 4SFP+ Switch", "2930F", 48, 4, "SFP+"),
    _m("JL261A", "Aruba 2930F 24G PoE+ 4SFP+ Switch", "2930F", 24, 4, "SFP+", 370.0),
    _m("JL262A", "Aruba 2930F 48G PoE+ 4SFP+ Switch", "2930F", 48, 4, "SFP+", 370.0),
    # HPE Aruba 5400R zl2 modular chassis (firmware KB.16.x). PoE depends on modules and power supplies.
    _m("J9850A", "HPE Aruba 5406R zl2 Switch", "5400R", 0, 0, "", modular=True, slots="ABCDEF"),
    _m("J9821A", "HPE Aruba 5406R zl2 Switch", "5400R", 0, 0, "", modular=True, slots="ABCDEF"),
    _m("J9851A", "HPE Aruba 5412R zl2 Switch", "5400R", 0, 0, "", modular=True, slots="ABCDEFGHIJKL"),
    _m("J9822A", "HPE Aruba 5412R zl2 Switch", "5400R", 0, 0, "", modular=True, slots="ABCDEFGHIJKL"),
]}


def spec_for(product_number: str | None) -> ModelSpec | None:
    return MODELS.get(product_number or "")


def split_slot_port(name: str) -> tuple[str, int] | None:
    """'B24' -> ('B', 24); None for numbered or trunk ports."""
    m = _SLOT_PORT.match(name)
    return (m.group(1), int(m.group(2))) if m else None


def port_number(name: str) -> int | None:
    """Front-panel number of a fixed-port switch port; None for slot ports (A1) and trunks."""
    return int(name) if name.isdigit() else None


def default_if_index(name: str) -> int | None:
    if name.isdigit():
        return int(name)
    sp = split_slot_port(name)
    if sp:
        return (ord(sp[0]) - ord("A")) * SLOT_IFINDEX_STRIDE + sp[1]
    return None


def port_sort_key(name: str) -> tuple:
    """Natural order: 1 < 2 < 10, A1 < A2 < A10 < B1, then trunks."""
    if name.isdigit():
        return (0, "", int(name))
    sp = split_slot_port(name)
    if sp:
        return (1, sp[0], sp[1])
    m = re.match(r"^(\D*)(\d*)$", name)
    if m and m.group(2):
        return (2, m.group(1), int(m.group(2)))
    return (3, name, 0)


def port_type(spec: ModelSpec | None, name: str, *, poe_port: bool = False) -> str:
    """Physical port type from the model catalogue. Returns '' when it cannot be known (unknown model, or a module
    port on a chassis that has not reported PoE for it)."""
    if name.isdigit() and spec is not None and not spec.modular:
        n = int(name)
        if n > spec.access_ports:
            return spec.uplink_type
        return "10/100/1000T PoE+" if spec.poe else "10/100/1000T"
    if split_slot_port(name):
        return "PoE+" if poe_port else ""
    return ""
