"""Prompt composer: deterministic assembly of the engineered prompt from the model's analysis and library rows.
Sections are fixed so the result is inspectable (`ask --dry`) and its provenance is recorded."""
from __future__ import annotations

from typing import Dict, List, Optional


def build(raw: str, analysis: Dict, persona: Optional[Dict] = None, command: Optional[Dict] = None,
          skills: Optional[List[Dict]] = None, max_chars: int = 1800) -> tuple[str, List[Dict]]:
    """Return (engineered_prompt, provenance). persona/command/skills are library rows (name, kind, id, body)."""
    parts, src = [], []
    if persona and persona.get("body", "").strip():
        parts.append(f"## Role\nAct as '{persona['name']}'. Follow this role definition:\n{persona['body'].strip()[:max_chars]}")
        src.append({"id": persona["id"], "kind": persona["kind"], "name": persona["name"], "how": "role"})
    if analysis.get("goal"):
        parts.append(f"## Goal\n{analysis['goal']}")
    if command and command.get("body", "").strip():
        parts.append(f"## Procedure ({command['name']})\n{command['body'].strip()[:max_chars]}")
        src.append({"id": command["id"], "kind": command["kind"], "name": command["name"], "how": "procedure"})
    for s in (skills or [])[:2]:
        if s.get("body", "").strip():
            parts.append(f"## Reference: {s['name']} (apply where relevant)\n{s['body'].strip()[:max_chars // 2]}")
            src.append({"id": s["id"], "kind": s["kind"], "name": s["name"], "how": "reference"})
    if analysis.get("constraints"):
        parts.append("## Constraints\n" + "\n".join(f"- {c}" for c in analysis["constraints"]))
    parts.append(f"## Request (verbatim from the owner)\n{raw.strip()}")
    nt = analysis.get("named_things") or []
    if nt:
        parts.append(("Named things (verbatim): " + ", ".join(nt))[:400])
    acc = list(analysis.get("acceptance") or [])
    acc.append("Cite only files, commands and facts you actually checked; mark anything else `unverified:`.")
    parts.append("## Acceptance\n" + "\n".join(f"- {a}" for a in acc))
    if analysis.get("output_format"):
        parts.append(f"## Output format\n{analysis['output_format']}")
    return "\n\n".join(parts), src


def pick_tier(task_class: str, tiers: Dict[str, str], allowed_workers: set, default: str = "nim1",
              requested: str = "auto") -> tuple[str, str]:
    """Task class -> worker via config table; `requested` (strong/weak/auto) overrides the class mapping.
    weak = cheapest acceptable worker (default), strong = class-mapped worker, auto = class mapping."""
    if requested == "weak":
        return default, "tier weak -> " + default
    w = tiers.get(task_class) or tiers.get("other") or default
    if requested == "strong" and w not in allowed_workers:
        w = default
    if w in allowed_workers:
        return w, "tier"
    return default, f"tier {w} unavailable -> {default}"
