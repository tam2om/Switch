"""Simulated AOS-Switch REST API, served through an httpx MockTransport (no network)."""

from __future__ import annotations

import base64
import json
import re
import secrets

import httpx

from app.drivers.simulator import state as st
from app.drivers.simulator.state import FIRMWARE, MODEL_DESC, PRODUCT, ROM, SimSwitch

SIM_USER = "sim-rest"
SIM_PASSWORD = "sim-only-not-a-real-credential"  # noqa: S105 - simulator only, documented


def _resp(status: int, body: object = None) -> httpx.Response:
    return httpx.Response(status, json=body if body is not None else {})


def _err(status: int, msg: str) -> httpx.Response:
    return httpx.Response(status, json={"message": msg})


class SimRestHandler:
    def __init__(self, ip: str, sessions: dict[str, str] | None = None):
        self.ip = ip
        self.sessions = sessions if sessions is not None else {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        sw = st.store.get(self.ip)
        if sw is None or sw.offline:
            raise httpx.ConnectError("simulated switch unreachable", request=request)
        path = request.url.path
        if path == "/rest/version":
            return _resp(200, {"version_element": [{"version": f"v{i}"} for i in range(1, 8)]})
        m = re.match(r"^/rest/(v\d+)(/.*)$", path)
        if not m:
            return _err(404, "not found")
        sub = m.group(2)
        if sub == "/login-sessions":
            if request.method == "POST":
                body = json.loads(request.content or b"{}")
                if body.get("userName") != SIM_USER or body.get("password") != SIM_PASSWORD:
                    return _err(401, "Authentication failed")
                sid = secrets.token_hex(16)
                self.sessions[sid] = self.ip
                return _resp(201, {"uri": "/login-sessions", "cookie": f"sessionId={sid}"})
            if request.method == "DELETE":
                return _resp(204)
        cookie = request.headers.get("cookie", "")
        sid = cookie.removeprefix("sessionId=")
        if sid not in self.sessions:
            return _err(401, "Session expired")
        for prefix in sw.unsupported_rest:
            if sub.startswith(prefix):
                return _err(404, "Resource not found")
        try:
            return self._dispatch(request.method, sub, json.loads(request.content) if request.content else None)
        except KeyError as exc:
            return _err(404, f"not found: {exc}")
        except ValueError as exc:
            return _err(400, str(exc))

    # ---------- dispatch ----------
    def _dispatch(self, method: str, sub: str, body: dict | None) -> httpx.Response:
        ip = self.ip
        sw = st.store.get(ip)
        assert sw is not None
        if method == "GET":
            return self._get(sw, sub)
        if method == "PUT" and (m := re.match(r"^/ports/([^/]+)$", sub)):
            return st.mutate(ip, lambda s: self._put_port(s, m.group(1), body or {}))
        if method == "PUT" and (m := re.match(r"^/ports/([^/]+)/poe$", sub)):
            return st.mutate(ip, lambda s: self._put_poe(s, m.group(1), body or {}))
        if method == "POST" and sub == "/vlans":
            return st.mutate(ip, lambda s: self._post_vlan(s, body or {}))
        if method == "PUT" and (m := re.match(r"^/vlans/(\d+)$", sub)):
            return st.mutate(ip, lambda s: self._put_vlan(s, int(m.group(1)), body or {}))
        if method == "DELETE" and (m := re.match(r"^/vlans/(\d+)$", sub)):
            return st.mutate(ip, lambda s: self._delete_vlan(s, int(m.group(1))))
        if method == "POST" and sub == "/vlans-ports":
            return st.mutate(ip, lambda s: self._post_vlan_port(s, body or {}))
        if method == "DELETE" and (m := re.match(r"^/vlans-ports/(\d+)-(.+)$", sub)):
            return st.mutate(ip, lambda s: self._delete_vlan_port(s, int(m.group(1)), m.group(2)))
        if method == "POST" and sub == "/cli":
            return self._cli(sw, (body or {}).get("cmd", ""))
        return _err(405, "Method not allowed")

    def _get(self, sw: SimSwitch, sub: str) -> httpx.Response:
        if sub == "/system":
            return _resp(200, {"name": sw.hostname, "location": sw.location, "contact": "noc@example.invalid"})
        if sub == "/system/status":
            return _resp(200, {"name": sw.hostname, "serial_number": sw.serial, "firmware_version": FIRMWARE,
                               "rom_version": ROM, "hardware_revision": "0",
                               "product_model": f"{MODEL_DESC.replace('Aruba ', '')}",
                               "base_ethernet_address": {"version": "MAV_ETHERNET",
                                                         "octets": sw.base_mac.replace(":", "")}})
        if sub == "/ports":
            return _resp(200, {"port_element": [
                {"id": n, "name": p.description, "is_port_enabled": p.enabled, "is_port_up": sw.oper_up(p),
                 "config_mode": "PCM_" + {"auto": "AUTO", "10-half": "10HDX", "10-full": "10FDX", "100-half": "100HDX",
                                          "100-full": "100FDX", "1000-full": "1000FDX", "auto-10": "AUTO_10",
                                          "auto-100": "AUTO_100", "auto-1000": "AUTO_1000",
                                          "auto-10-100": "AUTO_10_100"}[p.config_mode],
                 "trunk_mode": "PTT_NONE", "lacp_status": "LAS_DISABLED", "trunk_group": ""}
                for n, p in sorted(sw.ports.items(), key=lambda kv: int(kv[0]))]})
        if sub == "/vlans":
            return _resp(200, {"vlan_element": [
                {"vlan_id": v, "name": n, "status": "VS_PORT_BASED", "type": "VT_STATIC",
                 "is_voice_enabled": v == 20, "is_management_vlan": v == sw.mgmt_vlan} for v, n in sorted(sw.vlans.items())]})
        if sub == "/vlans-ports":
            el = [{"vlan_id": v, "port_id": p, "port_mode": "POM_UNTAGGED"} for p, v in sw.untagged.items()]
            el += [{"vlan_id": v, "port_id": p, "port_mode": "POM_TAGGED_STATIC"} for p, vs in sw.tagged.items()
                   for v in vs]
            return _resp(200, {"vlan_port_element": el})
        if sub == "/poe/ports":
            return _resp(200, {"port_poe": [
                {"port_id": n, "is_poe_enabled": p.poe_enabled, "poe_priority": f"PPP_{p.poe_priority.upper()}",
                 "poe_allocation_method": f"PPAM_{p.poe_alloc.upper()}", "allocated_power_in_watts": p.poe_value,
                 "pre_standard_detect_enabled": False}
                for n, p in sorted(sw.ports.items(), key=lambda kv: int(kv[0])) if int(n) <= st.ACCESS_PORTS]})
        if sub == "/poe/ports/stats":
            return _resp(200, {"port_poe_stats": [
                {"port_id": n, "poe_detection_status": sw.poe_status(p), "power_class": p.poe_class or None,
                 "power_drawn_in_watts": sw.poe_drawn(p), "over_current_count": 1 if p.poe_fault else 0}
                for n, p in sorted(sw.ports.items(), key=lambda kv: int(kv[0])) if int(n) <= st.ACCESS_PORTS]})
        if sub == "/mac-table":
            return _resp(200, {"mac_table_entry_element": [
                {"mac_address": m["mac"].replace(":", "")[:6] + "-" + m["mac"].replace(":", "")[6:],
                 "port_id": m["port"], "vlan_id": m["vlan"]}
                for m in sw.macs if sw.oper_up(sw.ports[m["port"]])]})
        if sub == "/lldp/remote-device":
            return _resp(200, {"lldp_remote_device_element": [
                {"local_port": n["local_port"], "chassis_type": "CIT_MAC_ADDRESS", "chassis_id": n["chassis_id"],
                 "port_type": "PIT_LOCAL", "port_id": n["port_id"], "port_description": n["port_description"],
                 "system_name": n["system_name"], "system_description": n["system_description"],
                 "remote_management_address": [], "capabilities_enabled": ["CAP_BRIDGE"]}
                for n in sw.lldp if sw.oper_up(sw.ports[n["local_port"]])]})
        raise KeyError(sub)

    @staticmethod
    def _put_port(sw: SimSwitch, pid: str, body: dict) -> httpx.Response:
        p = sw.ports[pid]
        if "is_port_enabled" in body:
            p.enabled = bool(body["is_port_enabled"])
        if "name" in body:
            p.description = str(body["name"])[:64]
        if "config_mode" in body:
            mode = body["config_mode"].removeprefix("PCM_").lower().replace("hdx", "-half").replace("fdx", "-full")
            mode = mode.replace("_", "-")
            if mode not in ("auto", "10-half", "10-full", "100-half", "100-full", "1000-full", "auto-10", "auto-100",
                            "auto-1000", "auto-10-100"):
                raise ValueError("invalid config_mode")
            p.config_mode = mode
        return _resp(200, {"id": pid})

    @staticmethod
    def _put_poe(sw: SimSwitch, pid: str, body: dict) -> httpx.Response:
        if int(pid) > st.ACCESS_PORTS:
            raise ValueError("Port does not support PoE")
        p = sw.ports[pid]
        if "is_poe_enabled" in body:
            p.poe_enabled = bool(body["is_poe_enabled"])
        if "poe_priority" in body:
            p.poe_priority = body["poe_priority"].removeprefix("PPP_").lower()
        if "poe_allocation_method" in body:
            p.poe_alloc = body["poe_allocation_method"].removeprefix("PPAM_").lower()
        if "allocated_power_in_watts" in body:
            p.poe_value = int(body["allocated_power_in_watts"])
        return _resp(200, {"port_id": pid})

    @staticmethod
    def _post_vlan(sw: SimSwitch, body: dict) -> httpx.Response:
        vid = int(body["vlan_id"])
        if vid in sw.vlans:
            return _err(409, "VLAN already exists")
        if len(sw.vlans) >= 256:
            return _err(400, "Maximum VLANs reached")
        sw.vlans[vid] = body.get("name") or f"VLAN{vid}"
        return _resp(201, {"vlan_id": vid})

    @staticmethod
    def _put_vlan(sw: SimSwitch, vid: int, body: dict) -> httpx.Response:
        if vid not in sw.vlans:
            raise KeyError(vid)
        sw.vlans[vid] = body.get("name", sw.vlans[vid])
        return _resp(200, {"vlan_id": vid})

    @staticmethod
    def _delete_vlan(sw: SimSwitch, vid: int) -> httpx.Response:
        if vid == 1:
            return _err(400, "Cannot delete default VLAN")
        if vid == sw.mgmt_vlan:
            return _err(400, "Cannot delete management VLAN")
        if vid not in sw.vlans:
            raise KeyError(vid)
        del sw.vlans[vid]
        for p, v in list(sw.untagged.items()):
            if v == vid:
                sw.untagged[p] = 1
        for p in sw.tagged:
            sw.tagged[p] = [v for v in sw.tagged[p] if v != vid]
        return _resp(204)

    @staticmethod
    def _post_vlan_port(sw: SimSwitch, body: dict) -> httpx.Response:
        vid = int(body["vlan_id"])
        pid = str(body["port_id"])
        if vid not in sw.vlans:
            return _err(400, "VLAN does not exist")
        if pid not in sw.ports:
            raise KeyError(pid)
        if body.get("port_mode") == "POM_UNTAGGED":
            sw.untagged[pid] = vid
            sw.tagged[pid] = [v for v in sw.tagged.get(pid, []) if v != vid]
        else:
            if sw.untagged.get(pid) == vid:
                sw.untagged[pid] = 1 if vid != 1 else 1
            sw.tagged.setdefault(pid, [])
            if vid not in sw.tagged[pid]:
                sw.tagged[pid].append(vid)
        return _resp(201, {"vlan_id": vid, "port_id": pid})

    @staticmethod
    def _delete_vlan_port(sw: SimSwitch, vid: int, pid: str) -> httpx.Response:
        if sw.untagged.get(pid) == vid:
            sw.untagged[pid] = 1
        elif vid in sw.tagged.get(pid, []):
            sw.tagged[pid].remove(vid)
        else:
            raise KeyError(f"{vid}-{pid}")
        return _resp(204)

    def _cli(self, sw: SimSwitch, cmd: str) -> httpx.Response:
        if cmd == "show running-config":
            out = "Running configuration:\n\n" + sw.running_config()
        elif cmd == "write memory":
            st.mutate(self.ip, lambda s: setattr(s, "startup_config", s.running_config()))
            out = ""
        elif cmd == "show version":
            out = f"Image stamp: /ws/swbuildm/rel_yc_qaoff/code/build/tam(swbuildm_rel_yc_qaoff_rel_yc)\n{FIRMWARE}\n"
        else:
            return _resp(200, {"cmd": cmd, "status": "CCS_FAILURE", "error_msg": "Invalid input",
                               "result_base64_encoded": ""})
        return _resp(200, {"cmd": cmd, "status": "CCS_SUCCESS", "error_msg": "",
                           "result_base64_encoded": base64.b64encode(out.encode()).decode()})


def transport(ip: str) -> httpx.MockTransport:
    return httpx.MockTransport(SimRestHandler(ip))


__all__ = ["SIM_PASSWORD", "SIM_USER", "PRODUCT", "SimRestHandler", "transport"]
