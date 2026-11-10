"""Tools the LangGraph supervisor can call to dispatch work to agents."""
import os
import json
import subprocess
import uuid
import shutil
import glob
from typing import Dict, Any, Optional, List
from pathlib import Path

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, "Developer", "agent-router", "config")


def load_yaml(path: str) -> dict:
    """Load a YAML config file."""
    import yaml
    p = Path(path)
    if not p.exists():
        return {}
    with open(p) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Agent discovery — outer scan of PATH + agent config files
# ---------------------------------------------------------------------------

KNOWN_CLI_AGENTS = [
    {"id": "claude", "cli": "claude", "config_home": os.path.join(HOME, ".claude")},
    {"id": "codex", "cli": "codex", "config_home": os.path.join(HOME, ".codex")},
    {"id": "opencode", "cli": "opencode", "config_home": os.path.join(HOME, ".config", "opencode")},
    {"id": "cline", "cli": "cline", "config_home": os.path.join(HOME, ".vscode", "cline")},
    {"id": "kilo", "cli": "kilo", "config_home": os.path.join(HOME, ".kilo")},
    {"id": "hermes", "cli": "hermes", "config_home": os.path.join(HOME, ".hermes")},
    {"id": "gemini", "cli": "gemini", "config_home": os.path.join(HOME, ".gemini")},
]


def scan_cli_on_path() -> Dict[str, bool]:
    """Scan PATH for known agent CLIs. Returns {agent_id: found_bool}."""
    result = {}
    for entry in KNOWN_CLI_AGENTS:
        result[entry["id"]] = shutil.which(entry["cli"]) is not None
    return result


def scan_agent_configs() -> Dict[str, dict]:
    """Scan agent config directories for existing configuration."""
    result = {}
    for entry in KNOWN_CLI_AGENTS:
        ch = entry["config_home"]
        found = {}
        if os.path.isdir(ch):
            # Look for common config files
            for pattern in ("config.toml", "config.json", "settings.json", "AGENTS.md", "CLAUDE.md"):
                matches = glob.glob(os.path.join(ch, "**", pattern), recursive=True)
                if matches:
                    found[pattern] = matches[:3]
        result[entry["id"]] = {
            "config_home": ch,
            "exists": os.path.isdir(ch),
            "configs": found,
        }
    return result


def discover_agents() -> List[Dict[str, Any]]:
    """Auto-detect available agents from config + outer scan of PATH and config files."""
    agents_cfg = load_yaml(os.path.join(CONFIG_DIR, "agents.yaml"))
    agents = agents_cfg.get("agents", [])

    cli_found = scan_cli_on_path()
    config_info = scan_agent_configs()

    available = []
    for a in agents:
        aid = a.get("id", "")
        entry = {
            "cli_found": cli_found.get(aid, False),
            "config_home": config_info.get(aid, {}).get("config_home", ""),
            "config_exists": config_info.get(aid, {}).get("exists", False),
            "agent_configs": config_info.get(aid, {}).get("configs", {}),
            **a,
        }
        available.append(entry)

    # Also add any CLI found on PATH that isn't in agents.yaml
    known_ids = {a.get("id") for a in agents}
    for aid, found in cli_found.items():
        if found and aid not in known_ids:
            available.append({
                "id": aid,
                "cli": aid,
                "cli_found": True,
                "config_home": config_info.get(aid, {}).get("config_home", ""),
                "config_exists": config_info.get(aid, {}).get("exists", False),
                "agent_configs": config_info.get(aid, {}).get("configs", {}),
                "model": "unknown",
                "provider": "cli",
                "write_access": False,
                "route_reasons": [],
                "skills": [],
                "note": "auto-discovered via PATH scan, add to agents.yaml to configure",
            })

    return available


def discover_skills() -> List[Dict[str, Any]]:
    """Load skills from skills.yaml and also scan skills directories."""
    skills_cfg = load_yaml(os.path.join(CONFIG_DIR, "skills.yaml"))
    skills = skills_cfg.get("skills", [])

    # Also scan ~/.claude/skills/ and ~/.agent-skills/ for SKILL.md files
    skill_dirs = [
        os.path.join(HOME, ".claude", "skills"),
        os.path.join(HOME, ".agent-skills"),
    ]
    seen_ids = {s.get("id") for s in skills}
    for sd in skill_dirs:
        if not os.path.isdir(sd):
            continue
        for skill_dir in sorted(Path(sd).iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                sid = skill_dir.name
                if sid in seen_ids:
                    continue
                # Read frontmatter
                import re
                text = skill_md.read_text(errors="ignore")
                m = re.match(r"---\n(.*?)\n---", text, re.S)
                desc = ""
                name = sid
                if m:
                    for line in m.group(1).splitlines():
                        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
                        if km:
                            if km.group(1) == "description":
                                desc = km.group(2).strip().strip('"').strip("'")
                            if km.group(1) == "name":
                                name = km.group(2).strip().strip('"').strip("'")
                skills.append({
                    "id": sid,
                    "path": str(skill_md),
                    "category": "auto-discovered",
                    "description": desc or f"Auto-discovered skill: {name}",
                    "source": sd,
                })
                seen_ids.add(sid)

    return skills


def discover_lanes() -> List[Dict[str, Any]]:
    """Load dispatch lanes from lanes.yaml."""
    lanes_cfg = load_yaml(os.path.join(CONFIG_DIR, "lanes.yaml"))
    return lanes_cfg.get("lanes", [])


def discover_projects() -> List[Dict[str, Any]]:
    """Load projects from projects.yaml and auto-discover AGENTS.md dirs."""
    projects_cfg = load_yaml(os.path.join(CONFIG_DIR, "projects.yaml"))
    projects = projects_cfg.get("projects", [])

    # Auto-discover directories with AGENTS.md in project roots
    project_roots_cfg = load_yaml(os.path.join(CONFIG_DIR, "config.yaml"))
    roots = project_roots_cfg.get("project_roots") or []
    seen_paths = {p.get("path") for p in projects if p.get("path")}

    for root in roots:
        if not root:
            continue
        expanded = os.path.expanduser(root)
        if not os.path.isdir(expanded):
            continue
        # Handle glob patterns like ~/bp-*
        if "*" in root:
            matches = glob.glob(expanded)
        else:
            matches = [expanded]
        for m in matches:
            if not m or not os.path.isdir(m):
                continue
            agents_md = os.path.join(m, "AGENTS.md")
            claude_md = os.path.join(m, "CLAUDE.md")
            if os.path.exists(agents_md) or os.path.exists(claude_md):
                if m in seen_paths:
                    continue
                projects.append({
                    "id": os.path.basename(m),
                    "path": m,
                    "name": os.path.basename(m),
                    "type": "auto-discovered",
                    "default_agent": "claude",
                    "default_model": "claude-sonnet-5-5",
                    "context_files": [f for f in ["AGENTS.md", "CLAUDE.md"] if os.path.exists(os.path.join(m, f))],
                    "preferred_lanes": ["build", "review-roast", "ops-repair"],
                })
                seen_paths.add(m)

    return projects


def discover_models() -> List[Dict[str, Any]]:
    """Load models from models.yaml."""
    models_cfg = load_yaml(os.path.join(CONFIG_DIR, "models.yaml"))
    return models_cfg.get("models", [])


# ---------------------------------------------------------------------------
# Packet building
# ---------------------------------------------------------------------------

def build_packet(
    lane: str,
    agent: str,
    project: str,
    user_input: str,
    skills: List[str],
    acceptance: str,
    forbidden: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a dispatch packet using the orchestration-prompts template."""
    packet = {
        "lane": lane,
        "agent": agent,
        "project": project,
        "goal": user_input,
        "skills_to_read": skills,
        "inputs": [user_input],
        "allowed_tools": "",
        "forbidden": forbidden or ["send", "spend", "delete", "push", "auth/DNS/mail config"],
        "output_path": f"~/Developer/agent-router/cards/{uuid.uuid4().hex[:8]}.md",
        "acceptance_check": acceptance,
        "budget": "10 minutes / 20 tool calls",
        "report": "<=15 lines: done / evidence (N of M) / blocked / next",
    }
    return packet


# ---------------------------------------------------------------------------
# Agent dispatch launchers
# ---------------------------------------------------------------------------

def launch_orca_agent(agent_id: str, packet: Dict[str, Any]) -> str:
    """Launch an agent via Orca CLI."""
    agents_cfg = load_yaml(os.path.join(CONFIG_DIR, "agents.yaml"))
    agent = next((a for a in agents_cfg.get("agents", []) if a["id"] == agent_id), None)
    if not agent:
        raise ValueError(f"Agent {agent_id} not found in config")

    launch_cmd = agent["launch_cmd"].format(
        packet=json.dumps(packet),
        dir=packet.get("project_context", {}).get("path", "~"),
        mode="workspace-write" if agent.get("write_access") else "read-only",
    )

    try:
        result = subprocess.run(
            launch_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return result.stdout or result.stderr or "No output"
    except subprocess.TimeoutExpired:
        return "Agent execution timed out after 120 seconds"
    except Exception as e:
        return f"Error launching agent: {e}"


def launch_codex_exec(packet: Dict[str, Any], mode: str = "workspace-write") -> str:
    """Launch Codex CLI exec."""
    dir_path = packet.get("project_context", {}).get("path", "~")
    cmd = f"codex exec -p delegated -C {dir_path} -s {mode} '{json.dumps(packet)}' </dev/null"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return result.stdout or result.stderr or "No output"
    except subprocess.TimeoutExpired:
        return "Codex execution timed out after 120 seconds"
    except Exception as e:
        return f"Error launching Codex: {e}"


def launch_nim_call(model: str, packet: Dict[str, Any]) -> str:
    """Launch a NIM model call directly (bypasses OpenCode/Zed)."""
    nim_call_path = os.path.join(HOME, "memory-vault", "scripts", "nim_call.py")
    venv_python = os.path.join(HOME, ".memory", "venv", "bin", "python")
    cmd = f"{venv_python} {nim_call_path} nim:{model} '{json.dumps(packet)}' </dev/null"
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
        return result.stdout or result.stderr or "No output"
    except subprocess.TimeoutExpired:
        return "NIM call timed out after 120 seconds"
    except Exception as e:
        return f"Error calling NIM: {e}"


def dispatch_to_agent(
    agent_id: str,
    packet: Dict[str, Any],
    lane: str,
) -> str:
    """Dispatch a packet to the appropriate agent launcher."""
    agents_cfg = load_yaml(os.path.join(CONFIG_DIR, "agents.yaml"))
    agent = next((a for a in agents_cfg.get("agents", []) if a["id"] == agent_id), None)
    if not agent:
        return f"Error: agent {agent_id} not found"

    cli = agent.get("cli", "")

    if cli == "claude":
        return launch_orca_agent(agent_id, packet)
    elif cli == "codex":
        mode = "workspace-write" if agent.get("write_access") else "read-only"
        return launch_codex_exec(packet, mode)
    elif cli == "nim_call.py":
        model = agent.get("model", "nemotron-3.5-super-vl-120b-a12b")
        return launch_nim_call(model, packet)
    elif cli == "opencode":
        return launch_orca_agent(agent_id, packet)  # via Orca
    elif cli == "hermes":
        return launch_orca_agent(agent_id, packet)  # via Orca/hermes
    else:
        return f"Unknown agent CLI: {cli}"


def check_gate_words(text: str) -> Optional[str]:
    """Check if text contains gate words that require human approval."""
    gate_words = ["send", "spend", "deploy", "approve", "submit", "push", "delete", "auth"]
    lower = text.lower()
    for word in gate_words:
        if word in lower:
            return word
    return None
