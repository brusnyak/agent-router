"""Packet parsing: name, goal, allowed_writes (globs relative to cwd), acceptance, receipt.

Packet format (leads/out/packets/TEMPLATE.md): ``Key: value`` sections, one known key per
section, values run until the next known key.  Section keys: Goal, Context, Method, Allowed
writes, Acceptance, Output file format, Stop rules, Final reply.  'Allowed writes' may be
bullet or comma separated; absent/unknown means no writes (read-only packet).
"""
from __future__ import annotations

import os
import re
from typing import Any

_SECTIONS = (
    "Goal", "Context", "Method", "Allowed writes", "Acceptance",
    "Output file format", "Stop rules", "Final reply", "Build",
)
_HEADER = re.compile(r"^(" + "|".join(re.escape(k) for k in _SECTIONS) + r"):\s*(.*)$")


def parse_packet(path: str) -> dict[str, Any]:
    """Parse a packet file into {name, goal, allowed_writes, acceptance, receipt}."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    name = os.path.splitext(os.path.basename(path))[0]
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        m = _HEADER.match(line)
        if m:
            current = m.group(1)
            if m.group(2).strip():
                sections.setdefault(current, []).append(m.group(2).strip())
        elif current is not None:
            sections.setdefault(current, []).append(line)
    joined = {k: "\n".join(v).strip() for k, v in sections.items()}
    return {
        "name": name,
        "path": os.path.abspath(path),
        "goal": joined.get("Goal", ""),
        "allowed_writes": _parse_allowed(joined.get("Allowed writes", "")),
        "acceptance": joined.get("Acceptance", ""),
        "receipt": joined.get("Output file format", "").split()[0] if joined.get("Output file format") else "",
    }


def _parse_allowed(raw: str) -> list[str]:
    parts: list[str] = []
    for line in raw.splitlines():
        line = re.sub(r"^[-*•]\s+", "", line).strip()
        if not line:
            continue
        for part in line.split(","):
            part = part.strip()
            if part:
                parts.append(part)
    return parts
