"""AOS-Switch REST API client (HTTPS only).

Session-based authentication: POST /rest/vN/login-sessions returns a "sessionId=..." cookie that must be sent on
subsequent requests. Sessions are closed with DELETE /rest/vN/login-sessions. AOS-Switch limits concurrent REST
sessions per switch, so the client always logs out on close and retries once on 401 (expired session).
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx

from app.drivers.aruba.aos_switch.capabilities import MAX_REST_VERSION, MIN_REST_VERSION
from app.drivers.base import DriverError

log = logging.getLogger(__name__)


class RestClient:
    def __init__(self, host: str, username: str, password: str, *, timeout: float = 10.0, verify: bool | str = True,
                 max_retries: int = 2, transport: httpx.BaseTransport | None = None, api_version: str | None = None):
        if not host:
            raise DriverError("config", "REST host is required", protocol="rest")
        self.host = host
        self._username = username
        self._password = password
        self.max_retries = max_retries
        self.api_version = api_version
        self._cookie: str | None = None
        self._client = httpx.Client(base_url=f"https://{host}", timeout=timeout, verify=verify, transport=transport,
                                    follow_redirects=False, headers={"Accept": "application/json"})

    # ---- session management ----
    def negotiate_version(self) -> str:
        if self.api_version:
            return self.api_version
        try:
            r = self._client.get("/rest/version")
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from exc
        if r.status_code != 200:
            raise DriverError("rest_unavailable", f"GET /rest/version returned HTTP {r.status_code}", protocol="rest")
        versions = []
        for item in r.json().get("version_element", []):
            v = str(item.get("version", "")).lstrip("v")
            if v.isdigit():
                versions.append(int(v))
        usable = [v for v in versions if MIN_REST_VERSION <= v <= MAX_REST_VERSION]
        if not usable:
            raise DriverError("rest_version", f"No supported REST API version offered (device: {versions})",
                              protocol="rest")
        self.api_version = f"v{max(usable)}"
        return self.api_version

    def login(self) -> None:
        ver = self.negotiate_version()
        try:
            r = self._client.post(f"/rest/{ver}/login-sessions",
                                  json={"userName": self._username, "password": self._password})
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from exc
        if r.status_code in (401, 403):
            raise DriverError("auth_failed", "REST authentication failed", protocol="rest")
        if r.status_code not in (200, 201):
            raise DriverError("rest_error", f"REST login returned HTTP {r.status_code}", protocol="rest",
                              retriable=r.status_code >= 500)
        cookie = r.json().get("cookie") or ""
        if not cookie.startswith("sessionId="):
            raise DriverError("rest_error", "REST login response did not include a session cookie", protocol="rest")
        self._cookie = cookie

    def logout(self) -> None:
        if not self._cookie or not self.api_version:
            return
        try:
            self._client.delete(f"/rest/{self.api_version}/login-sessions", headers={"Cookie": self._cookie})
        except httpx.HTTPError:
            log.debug("REST logout failed for %s", self.host)
        finally:
            self._cookie = None

    def close(self) -> None:
        self.logout()
        self._client.close()

    # ---- requests ----
    def request(self, method: str, path: str, json: Any = None, *, expect: tuple[int, ...] = (200, 201, 204)) -> Any:
        if self._cookie is None:
            self.login()
        attempt = 0
        relogged = False
        while True:
            attempt += 1
            try:
                r = self._client.request(method, f"/rest/{self.api_version}{path}", json=json,
                                         headers={"Cookie": self._cookie or ""})
            except httpx.HTTPError as exc:
                err = self._transport_error(exc)
                if attempt <= self.max_retries and method == "GET":
                    time.sleep(min(0.5 * attempt, 2.0))
                    continue
                raise err from exc
            if r.status_code == 401 and not relogged:
                relogged = True
                self._cookie = None
                self.login()
                continue
            if r.status_code in expect:
                if r.status_code == 204 or not r.content:
                    return {}
                return r.json()
            if r.status_code == 404:
                raise DriverError("not_found", f"{method} {path}: resource not found on device", protocol="rest",
                                  details={"status": 404})
            if r.status_code in (405, 501):
                raise DriverError("unsupported", f"{method} {path} is not supported by this firmware",
                                  protocol="rest", details={"status": r.status_code})
            if r.status_code >= 500 and attempt <= self.max_retries and method == "GET":
                time.sleep(min(0.5 * attempt, 2.0))
                continue
            message = ""
            try:
                body = r.json()
                message = body.get("message") or body.get("error_msg") or ""
            except ValueError:
                message = r.text[:200]
            raise DriverError("rest_error", f"{method} {path} failed: HTTP {r.status_code} {message}".strip(),
                              protocol="rest", retriable=r.status_code >= 500, details={"status": r.status_code})

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def put(self, path: str, body: Any) -> Any:
        return self.request("PUT", path, body)

    def post(self, path: str, body: Any) -> Any:
        return self.request("POST", path, body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def cli(self, command: str) -> str:
        """Run one allow-listed CLI command through the REST /cli resource and return decoded output."""
        res = self.post("/cli", {"cmd": command})
        status = res.get("status", "")
        if status and status != "CCS_SUCCESS":
            raise DriverError("cli_failed", f"CLI '{command.split()[0]}' failed: {res.get('error_msg', status)}",
                              protocol="rest-cli")
        raw = res.get("result_base64_encoded")
        if raw is None:
            return res.get("result", "")
        return base64.b64decode(raw).decode(errors="replace")

    @staticmethod
    def _transport_error(exc: httpx.HTTPError) -> DriverError:
        if isinstance(exc, httpx.TimeoutException):
            return DriverError("timeout", "REST request timed out", protocol="rest", retriable=True)
        if isinstance(exc, httpx.ConnectError) and "CERTIFICATE" in str(exc).upper():
            return DriverError("tls_error", "TLS certificate verification failed", protocol="rest")
        return DriverError("unreachable", f"REST connection failed: {exc.__class__.__name__}", protocol="rest",
                           retriable=True)
