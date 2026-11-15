"""Zabbix JSON-RPC client (API token authentication, Zabbix 5.4+)."""

from __future__ import annotations

from typing import Any

import httpx


class IntegrationError(Exception):
    pass


class ZabbixClient:
    def __init__(self, url: str, token: str, *, verify: bool = True, transport: httpx.BaseTransport | None = None,
                 timeout: float = 15.0):
        base = url.rstrip("/")
        self.endpoint = base if base.endswith("api_jsonrpc.php") else f"{base}/api_jsonrpc.php"
        self.web = base.removesuffix("/api_jsonrpc.php")
        self._token = token
        self._client = httpx.Client(verify=verify, timeout=timeout, transport=transport)
        self._id = 0

    def call(self, method: str, params: Any) -> Any:
        self._id += 1
        try:
            r = self._client.post(self.endpoint, json={"jsonrpc": "2.0", "method": method, "params": params,
                                                       "id": self._id},
                                  headers={"Authorization": f"Bearer {self._token}",
                                           "Content-Type": "application/json-rpc"})
        except httpx.HTTPError as exc:
            raise IntegrationError(f"Zabbix unreachable: {exc.__class__.__name__}") from exc
        if r.status_code != 200:
            raise IntegrationError(f"Zabbix returned HTTP {r.status_code}")
        body = r.json()
        if "error" in body:
            raise IntegrationError(f"Zabbix error: {body['error'].get('data') or body['error'].get('message')}")
        return body.get("result")

    def version(self) -> str:
        r = self._client.post(self.endpoint, json={"jsonrpc": "2.0", "method": "apiinfo.version", "params": {},
                                                   "id": 0})
        return r.json().get("result", "")

    def hosts(self, group: str | None = None) -> list[dict]:
        params: dict = {"output": ["hostid", "host", "name", "status"], "selectInterfaces": ["ip", "type", "main"],
                        "selectInventory": ["serialno_a", "location", "model"]}
        if group:
            groups = self.call("hostgroup.get", {"output": ["groupid"], "filter": {"name": [group]}})
            if not groups:
                return []
            params["groupids"] = [g["groupid"] for g in groups]
        return self.call("host.get", params)

    def problems(self, hostids: list[str]) -> list[dict]:
        if not hostids:
            return []
        return self.call("problem.get", {"hostids": hostids, "output": ["eventid", "objectid", "name", "severity",
                                                                         "clock", "acknowledged"],
                                         "selectHosts": ["hostid"], "recent": True, "sortfield": ["eventid"],
                                         "sortorder": "DESC", "limit": 500}) or []

    def host_url(self, hostid: str) -> str:
        return f"{self.web}/zabbix.php?action=latest.view&hostids%5B%5D={hostid}"

    def close(self) -> None:
        self._client.close()
