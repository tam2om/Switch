"""Aruba AirWave (AMP) client: form login, then XML APIs (ap_list.xml)."""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: S405 - parsed with a hardened parser below

import httpx

from app.integrations.zabbix import IntegrationError


def _safe_parse(text: str) -> ET.Element:
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise IntegrationError("AirWave response contains a DTD; refusing to parse")
    return ET.fromstring(text)  # noqa: S314 - DTD/entities rejected above


class AirWaveClient:
    def __init__(self, url: str, username: str, password: str, *, verify: bool = True,
                 transport: httpx.BaseTransport | None = None, timeout: float = 20.0):
        self.base = url.rstrip("/")
        self._client = httpx.Client(verify=verify, timeout=timeout, transport=transport, follow_redirects=False)
        self._user, self._pw = username, password
        self._logged_in = False

    def login(self) -> None:
        try:
            r = self._client.post(f"{self.base}/LOGIN", data={"credential_0": self._user, "credential_1": self._pw,
                                                               "destination": "/", "login": "Log In"})
        except httpx.HTTPError as exc:
            raise IntegrationError(f"AirWave unreachable: {exc.__class__.__name__}") from exc
        if r.status_code not in (200, 302) or not any("AMPAuth" in name for name in self._client.cookies.keys()):
            raise IntegrationError("AirWave login failed")
        self._logged_in = True

    def devices(self) -> list[dict]:
        if not self._logged_in:
            self.login()
        r = self._client.get(f"{self.base}/ap_list.xml")
        if r.status_code != 200:
            raise IntegrationError(f"AirWave ap_list.xml returned HTTP {r.status_code}")
        root = _safe_parse(r.text)
        out = []
        for ap in root.iter("ap"):
            def t(tag: str, el: ET.Element = ap) -> str:
                node = el.find(tag)
                return (node.text or "").strip() if node is not None and node.text else ""

            out.append({"id": ap.get("id"), "name": t("name"), "ip": t("lan_ip"), "mac": t("lan_mac"),
                        "model": t("model"), "firmware": t("firmware"), "serial": t("serial_number"),
                        "device_category": t("device_category"), "is_up": t("is_up") == "true",
                        "group": t("group")})
        return out

    def device_url(self, device_id: str) -> str:
        return f"{self.base}/ap_monitoring?id={device_id}"

    def close(self) -> None:
        self._client.close()
