"""Configuration retrieval helpers."""

from __future__ import annotations

import re

_VOLATILE = [
    re.compile(r"^; .*Configuration Editor; Created on release.*$"),
    re.compile(r"^; Ver #.*$"),
    re.compile(r"^Running configuration:\s*$"),
    re.compile(r"^Startup configuration:\s*$"),
]


def normalize_config(text: str) -> str:
    """Strip banners and volatile header lines so that checksums reflect real configuration changes."""
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if any(p.match(line.strip()) for p in _VOLATILE):
            continue
        lines.append(line.rstrip())
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


def looks_like_config(text: str) -> bool:
    return "hostname" in text and ("vlan " in text or "interface " in text)


_IFACE_RE = re.compile(r"^interface\s+(\S+)\s*$")
_SPEED_RE = re.compile(r"^\s+speed-duplex\s+(\S+)\s*$")


def port_speed_modes(config: str) -> dict[str, str]:
    """Configured speed-duplex per port from a running-config. Ports without a `speed-duplex` line are 'auto'
    (AOS-Switch only writes non-default settings); ports never mentioned are absent from the result."""
    out: dict[str, str] = {}
    current: str | None = None
    for line in config.splitlines():
        m = _IFACE_RE.match(line)
        if m:
            current = m.group(1)
            out.setdefault(current, "auto")
            continue
        if current is None:
            continue
        if line.strip() == "exit" or not line.startswith((" ", "\t")):
            current = None
            continue
        s = _SPEED_RE.match(line)
        if s:
            out[current] = s.group(1)
    return out
