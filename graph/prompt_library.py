"""Prompt library — loads SKILL.md files, orchestrates prompts, builds dispatch packets.

The prompt library is the system's memory of *how* to do work. It loads:
- SKILL.md files from ~/.claude/skills/ and ~/.agent-skills/ (capabilities + procedures)
- orchestration-prompts/SKILL.md (T1–T6 packet templates)
- dispatch-routes.json (lane definitions with acceptance checks, forbidden actions)
- Project AGENTS.md / CLAUDE.md (project-specific conventions, constraints, preferred agents)

It builds the system prompt injected into each agent and the dispatch packet
sent to the worker.
"""
from __future__ import annotations

import os
import re
import json
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, "Developer", "agent-router", "config")


# ---------------------------------------------------------------------------
# Skill loading
# ---------------------------------------------------------------------------

def _frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from a SKILL.md file."""
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if km:
            meta[km.group(1)] = km.group(2).strip().strip('"').strip("'")
    body = text[m.end():]
    return meta, body


def load_skill(skill_path: str) -> Optional[Dict[str, Any]]:
    """Load a single SKILL.md file into a skill dict."""
    p = Path(skill_path)
    if not p.exists():
        return None
    text = p.read_text(errors="ignore")
    meta, body = _frontmatter(text)
    return {
        "id": p.parent.name,
        "path": str(p),
        "name": meta.get("name", p.parent.name),
        "description": meta.get("description", ""),
        "body": body[:2000],  # truncate for context budget
        "full_body": body,
    }


def load_all_skills() -> List[Dict[str, Any]]:
    """Load all skills from ~/.claude/skills/ and ~/.agent-skills/."""
    skills = []
    seen = set()
    for sd in [os.path.join(HOME, ".claude", "skills"), os.path.join(HOME, ".agent-skills")]:
        if not os.path.isdir(sd):
            continue
        for skill_dir in sorted(Path(sd).iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                sid = skill_dir.name
                if sid in seen:
                    continue
                skill = load_skill(str(skill_md))
                if skill:
                    skill["source"] = sd
                    skills.append(skill)
                    seen.add(sid)
    return skills


def get_skill_brief(skill_id: str) -> Optional[str]:
    """Return the one-line description + key guidance for a skill (for injection)."""
    for s in load_all_skills():
        if s["id"] == skill_id:
            return f"{s['name']}: {s['description']}\n{s['body'][:500]}"
    return None


# ---------------------------------------------------------------------------
# Lane definitions
# ---------------------------------------------------------------------------

def load_lanes() -> List[Dict[str, Any]]:
    """Load dispatch lanes from lanes.yaml."""
    path = os.path.join(CONFIG_DIR, "lanes.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("lanes", [])


def get_lane(lane_id: str) -> Optional[Dict[str, Any]]:
    """Get a single lane definition by id."""
    for lane in load_lanes():
        if lane.get("id") == lane_id:
            return lane
    return None


# ---------------------------------------------------------------------------
# Project context
# ---------------------------------------------------------------------------

def load_project_context(project_id: str) -> Optional[Dict[str, Any]]:
    """Load a project's context: AGENTS.md, CLAUDE.md, preferred lanes/agents."""
    path = os.path.join(CONFIG_DIR, "projects.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    for p in cfg.get("projects", []):
        if p.get("id") == project_id or p.get("path") == project_id:
            # Load AGENTS.md / CLAUDE.md if they exist
            context = dict(p)
            proj_path = p.get("path") or ""
            for cf in p.get("context_files", []):
                full = os.path.join(proj_path, cf) if proj_path and not os.path.isabs(cf) else (cf if os.path.isabs(cf) else "")
                if proj_path and os.path.exists(full):
                    try:
                        content = Path(full).read_text(errors="ignore")[:3000]
                        context[f"_{cf}_content"] = content
                    except Exception:
                        pass
            return context
    return None


# ---------------------------------------------------------------------------
# Packet building with prompt library injection
# ---------------------------------------------------------------------------

ORCHESTRATION_HEADER = """OUTPUT STYLE: caveman. Result first, no openers/recaps. Return <=10 lines; full report to <abs path>.
OWNER WORDS (verbatim): "<quote>"
PROFILE (verbatim, do not infer): <only lines relevant, from owner-facts.md / cv>
HARD STOPS: no sends, no sign-ups, no spend, no deletes, no pushes, no secrets printed. Stop after 2 failed attempts and report the blocker.
LIMITS: <=2 sub-tasks per packet. After EACH sub-task append its findings to the report file before starting the next. Browser: max 3 tabs, close each tab when its page is read; non-browser workers use curl/WebFetch, not Neo. Allowed writes outside the repo: <path or none>.
EVIDENCE: label each claim proven (command/url/file:line) | assumed | unknown. Unread = say "N of M read".
ACCEPTANCE (caller runs): <command or check>
"""


def build_packet(
    lane_id: str,
    agent_id: str,
    project_id: str,
    user_input: str,
    skills: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a complete dispatch packet using the prompt library.

    The packet includes:
    - lane definition (acceptance check, forbidden actions, skills)
    - agent config (model, provider, write access)
    - project context (AGENTS.md/CLAUDE.md content, conventions)
    - skill briefs (loaded from SKILL.md files)
    - orchestration header (caveman rules, evidence requirements)
    - user input (verbatim)
    """
    lane = get_lane(lane_id) or {}
    project = load_project_context(project_id) or {}
    agent_config = {}
    import sys
    sys.path.insert(0, os.path.join(HOME, "Developer", "agent-router"))
    from graph.agent_base import load_agent_config
    agent_config = load_agent_config(agent_id) or {}

    lane_skills = lane.get("skills", [])
    if skills:
        lane_skills = skills

    # Load skill briefs
    skill_briefs = {}
    for sid in lane_skills:
        brief = get_skill_brief(sid)
        if brief:
            skill_briefs[sid] = brief

    packet = {
        "lane": lane_id,
        "lane_def": lane,
        "agent": agent_id,
        "agent_config": agent_config,
        "project": project_id,
        "project_context": project,
        "goal": user_input,
        "skills_to_read": lane_skills,
        "skill_briefs": skill_briefs,
        "inputs": [user_input],
        "allowed_tools": "",
        "forbidden": lane.get("never", ["send", "spend", "delete", "push", "auth/DNS/mail config"]),
        "output_path": f"~/Developer/agent-router/cards/{__import__('uuid').uuid4().hex[:8]}.md",
        "acceptance_check": lane.get("acceptance", "run acceptance check"),
        "budget": "10 minutes / 20 tool calls",
        "report": "<=15 lines: done / evidence (N of M) / blocked / next",
        "orchestration_header": ORCHESTRATION_HEADER,
    }
    return packet


def render_system_prompt(packet: Dict[str, Any]) -> str:
    """Render the full system prompt injected into the worker agent.

    Combines: orchestration header + lane definition + skill briefs +
    project context + agent constraints into one coherent prompt.
    """
    lines = []

    # Orchestration header
    lines.append(packet.get("orchestration_header", ""))
    lines.append("")

    # Lane definition
    lane = packet.get("lane_def", {})
    lines.append("## Dispatch Lane")
    lines.append(f"Lane: {packet.get('lane')}")
    lines.append(f"Acceptance: {lane.get('acceptance', 'run acceptance check')}")
    lines.append(f"Forbidden: {', '.join(packet.get('forbidden', []))}")
    lines.append("")

    # Skills
    if packet.get("skill_briefs"):
        lines.append("## Skills (read before executing)")
        for sid, brief in packet["skill_briefs"].items():
            lines.append(f"### {sid}")
            lines.append(brief)
            lines.append("")

    # Project context
    project = packet.get("project_context", {})
    if project:
        lines.append("## Project Context")
        for key, value in project.items():
            if key.startswith("_") and key.endswith("_content"):
                cf_name = key[1:-8]  # strip _ and _content
                lines.append(f"### {cf_name}")
                lines.append(str(value)[:2000])
                lines.append("")
        if project.get("preferred_lanes"):
            lines.append(f"Preferred lanes: {', '.join(project['preferred_lanes'])}")
        lines.append("")

    # Agent constraints
    agent_cfg = packet.get("agent_config", {})
    lines.append("## Agent Constraints")
    lines.append(f"Agent: {packet.get('agent')}")
    lines.append(f"Model: {agent_cfg.get('model', 'unknown')}")
    lines.append(f"Write access: {agent_cfg.get('write_access', False)}")
    lines.append("")

    # User input
    lines.append("## User Request")
    lines.append(packet.get("goal", ""))

    return "\n".join(lines)
