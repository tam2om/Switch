"""Deterministic Aruba 2540 simulator state.

SIMULATED DATA ONLY. Simulated switches are flagged is_simulated=True and driver='simulator' everywhere
(database, API, UI). Their state lives in Redis (shared by API and worker processes) or in memory for tests.
Counters are a deterministic function of wall-clock time, so traffic graphs move without persisting counters.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

FIRMWARE = "YC.16.11.0018"
ROM = "YC.16.01.0002"
PRODUCT = "JL356A"
MODEL_DESC = "Aruba JL356A 2540-24G-PoE+-4SFP+ Switch"
ACCESS_PORTS = 24
UPLINK_PORTS = [25, 26, 27, 28]
POE_BUDGET_W = 370.0

OUIS = [("00:1a:1e", "Aruba"), ("3c:2c:30", "Dell"), ("00:50:56", "VMware"), ("b4:96:91", "Intel"),
        ("00:0b:82", "Grandstream"), ("88:5a:92", "Cisco"), ("f4:39:09", "HP"), ("ac:1f:6b", "Supermicro"),
        ("00:04:f2", "Polycom"), ("ec:b1:d7", "HP Inc"), ("00:1b:17", "Palo Alto"), ("d4:ca:6d", "Axis")]


@dataclass
class SimPort:
    name: str
    description: str = ""
    enabled: bool = True
    config_mode: str = "auto"
    link: bool = False  # cable/device present
    speed: int = 1000
    poe_enabled: bool = True
    poe_priority: str = "low"
    poe_alloc: str = "usage"
    poe_value: int = 30
    poe_draw: float = 0.0  # watts drawn when delivering
    poe_class: str = ""
    poe_fault: bool = False
    base_rate: float = 0.0  # bytes/s average
    error_rate: float = 0.0  # errors/s
    flapping: bool = False


@dataclass
class SimSwitch:
    ip: str
    hostname: str
    serial: str
    base_mac: str
    location: str = ""
    seed: int = 0
    offline: bool = False
    slow: bool = False
    ports: dict[str, SimPort] = field(default_factory=dict)
    vlans: dict[int, str] = field(default_factory=dict)
    mgmt_vlan: int = 1
    untagged: dict[str, int] = field(default_factory=dict)  # port -> vlan
    tagged: dict[str, list[int]] = field(default_factory=dict)  # port -> vlans
    macs: list[dict] = field(default_factory=list)
    lldp: list[dict] = field(default_factory=list)
    extra_config: list[str] = field(default_factory=list)
    startup_config: str | None = None
    boot_epoch: float = 0.0
    rest_sessions: int = 0
    unsupported_rest: list[str] = field(default_factory=list)  # REST paths to answer 404 (fallback testing)

    # ---------- derived values ----------
    def uptime(self) -> int:
        return int(time.time() - self.boot_epoch)

    def cpu(self) -> int:
        t = time.time()
        return int(6 + 4 * (1 + math.sin(t / 300 + self.seed)) + (self.seed % 5))

    def mem_total(self) -> int:
        return 335_544_320

    def mem_free(self) -> int:
        return int(self.mem_total() * (0.62 - (self.seed % 7) / 100))

    def temperature(self) -> float:
        return round(34 + (self.seed % 9) + 2 * math.sin(time.time() / 900), 1)

    def oper_up(self, p: SimPort) -> bool:
        if not p.enabled or not p.link:
            return False
        if p.flapping:
            return int(time.time() / 45) % 2 == 0
        return True

    def counters(self, p: SimPort) -> dict[str, int]:
        t = time.time()
        rng = int(hashlib.md5(f"{self.ip}{p.name}".encode()).hexdigest()[:6], 16)  # noqa: S324 - not security
        phase = (rng % 1000) / 159.0
        rate = p.base_rate if self.oper_up(p) else 0.0
        # Integral of rate*(1+0.6 sin(wt+phase)) so derived bps varies smoothly over the day.
        w = 2 * math.pi / 3600
        integ = rate * (t + 0.6 * (-math.cos(w * t + phase)) / w)
        base = rng * 1000
        return {
            "in": int(base + integ * 0.7) % (2**64),
            "out": int(base + integ * 0.3) % (2**64),
            "in_err": int(p.error_rate * t / 10) % (2**32),
            "out_err": int(p.error_rate * t / 40) % (2**32),
            "in_disc": int(p.error_rate * t / 20) % (2**32),
            "out_disc": 0,
        }

    def poe_drawn(self, p: SimPort) -> float:
        if not (p.poe_enabled and p.link and p.enabled and p.poe_draw > 0 and not p.poe_fault):
            return 0.0
        return round(p.poe_draw * (1 + 0.05 * math.sin(time.time() / 120 + self.seed)), 1)

    def poe_status(self, p: SimPort) -> str:
        if not p.poe_enabled or not p.enabled:
            return "PPDS_DISABLED"
        if p.poe_fault:
            return "PPDS_FAULT"
        return "PPDS_DELIVERING" if self.poe_drawn(p) > 0 else "PPDS_SEARCHING"

    def poe_consumed(self) -> float:
        return round(sum(self.poe_drawn(p) for p in self.ports.values()), 1)

    # ---------- configuration rendering ----------
    def running_config(self) -> str:
        lines = [f"; {PRODUCT} Configuration Editor; Created on release #{FIRMWARE}", "; Ver #14:01.4f.f8.1d.9b.3f.bf.bb.ef.7c.59.fc.6b.fb.9f.fc.ff.ff.37.ef:05",
                 f'hostname "{self.hostname}"', "module 1 type jl356a"]
        if self.location:
            lines.append(f'snmp-server location "{self.location}"')
        lines += ["timesync sntp", "sntp unicast", "no telnet-server", "ip ssh filetransfer",
                  "no web-management plaintext", "snmpv3 enable"]
        lines += self.extra_config
        for name in sorted(self.ports, key=_port_key):
            p = self.ports[name]
            body = []
            if p.description:
                body.append(f'   name "{p.description}"')
            if not p.enabled:
                body.append("   disable")
            if p.config_mode != "auto":
                body.append(f"   speed-duplex {p.config_mode}")
            if int(name) <= ACCESS_PORTS:
                if not p.poe_enabled:
                    body.append("   no power-over-ethernet")
                elif p.poe_priority != "low":
                    body.append(f"   power-over-ethernet {p.poe_priority}")
                if p.poe_alloc != "usage":
                    body.append(f"   power-over-ethernet allocate-by {p.poe_alloc}"
                                + (f" value {p.poe_value}" if p.poe_alloc == "value" else ""))
            if body:
                lines += [f"interface {name}", *body, "   exit"]
        for vid in sorted(self.vlans):
            lines.append(f"vlan {vid}")
            lines.append(f'   name "{self.vlans[vid]}"')
            un = [p for p, v in self.untagged.items() if v == vid]
            tg = [p for p, vs in self.tagged.items() if vid in vs]
            if un:
                lines.append(f"   untagged {_compress(un)}")
            if tg:
                lines.append(f"   tagged {_compress(tg)}")
            if not un and not tg:
                lines.append("   no untagged 1-28")
            if vid == self.mgmt_vlan:
                lines.append(f"   ip address 10.{self.seed % 250}.{vid % 250}.{(self.seed % 200) + 10} 255.255.255.0")
            lines.append("   exit")
        lines.append(f"management-vlan {self.mgmt_vlan}")
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> SimSwitch:
        d = json.loads(raw)
        d["ports"] = {k: SimPort(**v) for k, v in d["ports"].items()}
        d["vlans"] = {int(k): v for k, v in d["vlans"].items()}
        return cls(**d)


def _port_key(name: str) -> tuple[int, str]:
    return (int(name), "") if name.isdigit() else (999, name)


def _compress(ports: list[str]) -> str:
    nums = sorted(int(p) for p in ports if p.isdigit())
    out: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(f"{nums[i]}-{nums[j]}" if j > i else str(nums[i]))
        i = j + 1
    return ",".join(out)


def build_switch(index: int, ip: str, total: int = 1, location: str = "") -> SimSwitch:
    """Create a deterministic simulated Aruba 2540 24G PoE+ switch."""
    rnd = random.Random(index * 7919 + 17)  # noqa: S311 - simulation only
    mac_tail = f"{(index >> 8) & 0xff:02x}:{index & 0xff:02x}:00"
    sw = SimSwitch(ip=ip, hostname=f"SIM-SW-{index:03d}", serial=f"SIMCN{index:06d}",
                   base_mac=f"02:5a:00:{mac_tail}", location=location or f"Sim Building {1 + index // 10}",
                   seed=index, boot_epoch=time.time() - rnd.randint(3600, 90 * 86400))
    sw.vlans = {1: "DEFAULT_VLAN", 10: "DATA", 20: "VOICE", 30: "CCTV", 99: "MGMT"}
    sw.mgmt_vlan = 99
    profile = ["pc", "phone", "ap", "camera", "printer", "empty"]
    for n in range(1, ACCESS_PORTS + 1):
        name = str(n)
        kind = profile[rnd.randint(0, 5)] if rnd.random() > 0.15 else "empty"
        p = SimPort(name=name)
        if kind != "empty":
            p.link = True
            p.speed = 1000 if kind in ("pc", "ap", "printer") else 100
            p.base_rate = {"pc": 60_000, "phone": 4_000, "ap": 400_000, "camera": 250_000, "printer": 2_000}[kind] \
                * rnd.uniform(0.3, 2.0)
            p.poe_draw = {"phone": 4.8, "ap": 13.5, "camera": 6.2}.get(kind, 0.0) * rnd.uniform(0.8, 1.3)
            p.poe_class = {"phone": "2", "ap": "4", "camera": "3"}.get(kind, "")
            p.description = {"pc": "Workstation", "phone": "IP Phone", "ap": "Wireless AP", "camera": "CCTV",
                             "printer": "Printer"}[kind]
            vlan = {"pc": 10, "phone": 10, "ap": 10, "camera": 30, "printer": 10}[kind]
            sw.untagged[name] = vlan
            if kind == "phone":
                sw.tagged[name] = [20]
            if kind == "ap":
                sw.tagged[name] = [20, 99]
            for k in range(1 if kind != "phone" else 2):
                oui, _vendor = OUIS[rnd.randint(0, len(OUIS) - 1)]
                mac = f"{oui}:{rnd.randint(0, 255):02x}:{rnd.randint(0, 255):02x}:{rnd.randint(0, 255):02x}"
                sw.macs.append({"mac": mac, "vlan": vlan if k == 0 else 20, "port": name})
        else:
            sw.untagged[name] = 1
        if rnd.random() < 0.03:
            p.error_rate = rnd.uniform(0.5, 5)
        sw.ports[name] = p
    for n in UPLINK_PORTS:
        name = str(n)
        p = SimPort(name=name, poe_enabled=False, speed=10000)
        if n in (25, 26):
            p.link = True
            p.base_rate = rnd.uniform(2e6, 2e7)
            p.description = "Uplink" if n == 25 else "Downlink"
        sw.ports[name] = p
        sw.tagged[name] = [10, 20, 30, 99]
        sw.untagged[name] = 1
    # Daisy-chain LLDP topology: port 25 -> previous switch port 26.
    if index > 1:
        prev = index - 1
        sw.lldp.append({"local_port": "25", "chassis_id": f"02:5a:00:{(prev >> 8) & 0xff:02x}:{prev & 0xff:02x}:00",
                        "port_id": "26", "port_description": "26", "system_name": f"SIM-SW-{prev:03d}",
                        "system_description": MODEL_DESC + f", revision {FIRMWARE}", "mgmt_ip": None})
    if index < total:
        nxt = index + 1
        sw.lldp.append({"local_port": "26", "chassis_id": f"02:5a:00:{(nxt >> 8) & 0xff:02x}:{nxt & 0xff:02x}:00",
                        "port_id": "25", "port_description": "25", "system_name": f"SIM-SW-{nxt:03d}",
                        "system_description": MODEL_DESC + f", revision {FIRMWARE}", "mgmt_ip": None})
    for p_name, p in sw.ports.items():
        if p.description == "Wireless AP":
            sw.lldp.append({"local_port": p_name, "chassis_id": "02:0b:86:00:00:%02x" % int(p_name),
                            "port_id": "eth0", "port_description": "eth0", "system_name": f"AP-{index:03d}-{p_name}",
                            "system_description": "Simulated access point", "mgmt_ip": None})
    sw.extra_config = []
    return sw


# ---------- storage (shared between processes via Redis) ----------

class SimStore:
    def __init__(self) -> None:
        self._mem: dict[str, str] = {}
        self._lock = threading.RLock()
        self._init_lock = threading.Lock()
        self._redis: Any = None
        self._redis_checked = False

    def _r(self) -> Any:
        if self._redis_checked:
            return self._redis
        # Polling runs in thread pools: initialise once under the lock so no thread sees a half-initialised store
        # (which previously made early lookups fall back to the empty in-memory dict and report timeouts).
        with self._init_lock:
            if self._redis_checked:
                return self._redis
            try:
                from app.core.config import get_settings

                s = get_settings()
                if s.environment != "test":
                    import redis

                    client = redis.Redis.from_url(s.redis_url, socket_timeout=2)
                    client.ping()
                    self._redis = client
            except Exception:  # noqa: BLE001
                self._redis = None
            self._redis_checked = True
        return self._redis

    def get(self, ip: str) -> SimSwitch | None:
        r = self._r()
        raw = r.get(f"anm:sim:{ip}") if r else self._mem.get(ip)
        if raw is None:
            return None
        return SimSwitch.from_json(raw if isinstance(raw, str) else raw.decode())

    def put(self, sw: SimSwitch) -> None:
        r = self._r()
        if r:
            r.set(f"anm:sim:{sw.ip}", sw.to_json())
        else:
            with self._lock:
                self._mem[sw.ip] = sw.to_json()

    def delete(self, ip: str) -> None:
        r = self._r()
        if r:
            r.delete(f"anm:sim:{ip}")
        else:
            self._mem.pop(ip, None)

    def clear(self) -> None:
        self._mem.clear()

    def lock(self, ip: str) -> Any:
        r = self._r()
        if r:
            return r.lock(f"anm:simlock:{ip}", timeout=10, blocking_timeout=10)
        return self._lock


store = SimStore()


def get_or_create(ip: str, index: int = 1, total: int = 1, location: str = "") -> SimSwitch:
    sw = store.get(ip)
    if sw is None:
        sw = build_switch(index, ip, total, location)
        store.put(sw)
    return sw


def mutate(ip: str, fn: Any) -> Any:
    with store.lock(ip):
        sw = store.get(ip)
        if sw is None:
            raise KeyError(ip)
        result = fn(sw)
        store.put(sw)
        return result
