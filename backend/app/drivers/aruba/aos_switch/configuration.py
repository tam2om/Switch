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
