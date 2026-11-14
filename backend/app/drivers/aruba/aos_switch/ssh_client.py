"""Controlled SSH/CLI access to AOS-Switch.

* Strict host-key verification: the switch's host key must have been fetched and explicitly trusted by an
  administrator (stored in switches.ssh_host_key). Unknown or changed keys abort the connection.
* Only allow-listed show commands and generated configuration lines (cli_commands.py) can be sent.
* Telnet is never used.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import tempfile
from typing import Protocol

from app.drivers.aruba.aos_switch.cli_commands import ALLOWED_SHOW_COMMANDS, assert_safe_line
from app.drivers.base import DriverError

log = logging.getLogger(__name__)

CLI_ERROR_MARKERS = ("Invalid input", "Ambiguous input", "Incomplete input", "% ", "Error:", "not supported",
                     "Unable to", "Value out of range")


class SshSession(Protocol):
    def show(self, command: str) -> str: ...

    def configure(self, lines: list[str]) -> str: ...

    def put_file(self, remote_path: str, content: str) -> None: ...

    def close(self) -> None: ...


def fingerprint(host_key_b64: str) -> str:
    raw = base64.b64decode(host_key_b64.split()[-1] if " " in host_key_b64 else host_key_b64)
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


def fetch_host_key(host: str, port: int = 22, timeout: float = 10.0) -> tuple[str, str]:  # pragma: no cover
    """Retrieve the server host key without authenticating (for trust-on-first-use approval by an admin)."""
    import socket

    import paramiko

    sock = socket.create_connection((host, port), timeout=timeout)
    t = paramiko.Transport(sock)
    try:
        t.start_client(timeout=timeout)
        key = t.get_remote_server_key()
        line = f"{key.get_name()} {key.get_base64()}"
        return line, fingerprint(key.get_base64())
    finally:
        t.close()


def check_cli_output(output: str, command: str) -> None:
    for marker in CLI_ERROR_MARKERS:
        if marker in output:
            raise DriverError("cli_rejected", f"Switch rejected command '{command}': {output.strip()[:200]}",
                              protocol="ssh")


class NetmikoSession:  # pragma: no cover - requires a device
    def __init__(self, host: str, username: str, password: str, host_key: str, *, port: int = 22,
                 timeout: float = 15.0):
        if not host_key:
            raise DriverError("host_key_untrusted", "SSH host key has not been trusted for this switch",
                              protocol="ssh")
        from netmiko import ConnectHandler
        from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

        self._kh = tempfile.NamedTemporaryFile("w", delete=False, prefix="anm_kh_")
        self._kh.write(f"{host} {host_key}\n" if port == 22 else f"[{host}]:{port} {host_key}\n")
        self._kh.close()
        try:
            self.conn = ConnectHandler(
                device_type="hp_procurve", host=host, username=username, password=password, port=port,
                ssh_strict=True, system_host_keys=False, alt_host_keys=True, alt_key_file=self._kh.name,
                timeout=timeout, conn_timeout=timeout, auth_timeout=timeout, fast_cli=False,
                allow_agent=False, use_keys=False,
            )
        except NetmikoAuthenticationException as exc:
            os.unlink(self._kh.name)
            raise DriverError("auth_failed", "SSH authentication failed", protocol="ssh") from exc
        except NetmikoTimeoutException as exc:
            os.unlink(self._kh.name)
            raise DriverError("timeout", "SSH connection timed out", protocol="ssh", retriable=True) from exc
        except Exception as exc:
            os.unlink(self._kh.name)
            if "host key" in str(exc).lower() or "BadHostKey" in exc.__class__.__name__:
                raise DriverError("host_key_mismatch", "SSH host key does not match the trusted key",
                                  protocol="ssh") from exc
            raise DriverError("unreachable", f"SSH connection failed: {exc.__class__.__name__}",
                              protocol="ssh", retriable=True) from exc
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    def show(self, command: str) -> str:
        if command not in ALLOWED_SHOW_COMMANDS:
            raise DriverError("not_allowed", f"Command not allow-listed: {command}", protocol="ssh")
        self.conn.send_command("no page", expect_string=r"#")
        return self.conn.send_command(command, read_timeout=60)

    def configure(self, lines: list[str]) -> str:
        for line in lines:
            assert_safe_line(line)
        out = self.conn.send_config_set(lines, cmd_verify=True, exit_config_mode=True)
        check_cli_output(out, lines[0] if lines else "")
        return out

    def put_file(self, remote_path: str, content: str) -> None:
        if remote_path not in ("/cfg/startup-config",):
            raise DriverError("not_allowed", "Only /cfg/startup-config may be written", protocol="ssh")
        sftp = self.conn.remote_conn.get_transport().open_sftp_client() if hasattr(self.conn, "remote_conn") \
            else None
        if sftp is None:
            raise DriverError("unsupported", "SFTP is unavailable on this session", protocol="ssh")
        try:
            sftp.putfo(io.BytesIO(content.encode()), remote_path)
        finally:
            sftp.close()

    def close(self) -> None:
        try:
            self.conn.disconnect()
        finally:
            if os.path.exists(self._kh.name):
                os.unlink(self._kh.name)
