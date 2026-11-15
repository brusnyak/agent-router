#!/usr/bin/env python3
"""
Dynamic orchestration graph for agent-router.

Reads from agent-router log files and produces a Mermaid sequence/graph
showing which models are invoked at which time for which task.
Run repeatedly to refresh — it's read-only, no state mutation.

Output: Mermaid flowchart to stdout (pipe to a file or render with Mermaid CLI).
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(os.path.expanduser("~/.agent-router"))
HOOK_SHADOW = BASE / "hook-shadow.jsonl"
OUTCOMES = BASE / "outcomes.jsonl"
ENFORCE = BASE / "enforce.jsonl"
DIGEST = BASE / "digest.log"

WORKER_MODEL_MAP = {
    "pi": "nim/nemotron-3.5-super-vl-120b",
    "claude": "claude-sonnet",
    "codex": "codex",
    "opencode": "nim/nemotron-3.5-super-vl-120b",
    "cline": "nim/nemotron-3.5-super-vl-120b",
}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _ts(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M:%S")


def build_graph(window_minutes: int = 60) -> str:
    now = datetime.now(tz=timezone.utc).timestamp()
    cutoff = now - window_minutes * 60

    hooks = _read_jsonl(HOOK_SHADOW)
    outcomes = _read_jsonl(OUTCOMES)
    enforces = _read_jsonl(ENFORCE)

    # Filter to window
    hooks = [h for h in hooks if h.get("ts", 0) > cutoff]
    outcomes = [o for o in outcomes if o.get("ts", 0) > cutoff]
    enforces = [e for e in enforces if e.get("ts", 0) > cutoff]

    # Build invocation chains by session
    sessions: dict[str, list[dict]] = defaultdict(list)
    for h in hooks:
        sid = h.get("session_id", "unknown")
        sessions[sid].append({
            "t": _ts(h.get("ts", 0)),
            "type": "prompt",
            "len": h.get("prompt_len", 0),
            "arm": h.get("arm", "shadow"),
            "abstention": h.get("abstention", ""),
        })
    for o in outcomes:
        sid = o.get("session_id", "unknown")
        sessions[sid].append({
            "t": _ts(o.get("ts", 0)),
            "type": "skill",
            "skill": o.get("skill", "unknown"),
        })
    for e in enforces:
        sid = e.get("sid", "unknown")
        sessions[sid].append({
            "t": _ts(e.get("ts", 0)),
            "type": "enforce",
            "action": e.get("action", "?"),
            "why": e.get("why", ""),
        })

    # Sort each session by time
    for sid in sessions:
        sessions[sid].sort(key=lambda x: x["t"])

    # Count stats
    total_prompts = len(hooks)
    total_outcomes = len(outcomes)
    total_enforces = len(enforces)
    blocked = sum(1 for e in enforces if e.get("action") == "block")
    allowed = sum(1 for e in enforces if e.get("action") == "allow")

    lines: list[str] = []
    lines.append("flowchart TD")
    lines.append("    subgraph Orchestration [Agent Router — Last {} min]".format(window_minutes))
    lines.append("        direction TB")
    lines.append("        A[User Prompt] --> B{Router}")
    lines.append("        B -->|skill match| C[Dispatch Worker]")
    lines.append("        B -->|no match| D[Direct Model]")
    lines.append("        C --> E[Execute]")
    lines.append("        D --> E")
    lines.append("        E --> F{Result}")
    lines.append("        F -->|ok| G[Return to User]")
    lines.append("        F -->|fail| H[Retry / Escalate]")
    lines.append("        H --> C")
    lines.append("    end")

    # Worker usage stats from outcomes
    skill_counts: dict[str, int] = defaultdict(int)
    for o in outcomes:
        skill_counts[o.get("skill", "unknown")] += 1

    if skill_counts:
        lines.append("")
        lines.append("    subgraph Skills [Tool Invocations]")
        for skill, count in sorted(skill_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"        S_{skill.replace('-', '_')}[{skill}: {count}x]")
        lines.append("    end")

    # Enforcement stats
    if enforces:
        lines.append("")
        lines.append("    subgraph Enforcement [Gate Decisions]")
        lines.append(f"        Blocked[{blocked} blocked]")
        lines.append(f"        Allowed[{allowed} allowed]")
        lines.append("    end")

    # Session timeline (most recent sessions)
    recent_sids = sorted(sessions.keys(), key=lambda s: max(
        (x["t"] for x in sessions[s]), default="00:00:00"
    ), reverse=True)[:5]

    if recent_sids:
        lines.append("")
        lines.append("    subgraph Recent Sessions")
        for sid in recent_sids:
            events = sessions[sid]
            short = sid[:8]
            lines.append(f"        subgraph S{short} [{len(events)} events]")
            prev = None
            for ev in events:
                label = f"{ev['t']} {ev['type']}"
                if ev['type'] == 'skill':
                    label += f"::{ev['skill']}"
                elif ev['type'] == 'enforce':
                    label += f"::{ev['action']}"
                node = f"N{short}_{ev['t'].replace(':', '')}"
                lines.append(f"            {node}[{label}]")
                if prev:
                    lines.append(f"            {prev} --> {node}")
                prev = node
            lines.append("        end")

    # Stats footer
    lines.append("")
    lines.append(f"    Stats[Total: {total_prompts} prompts · {total_outcomes} skills · {total_enforces} gates]")

    return "\n".join(lines)


def main() -> None:
    window = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    print(build_graph(window))


if __name__ == "__main__":
    main()
