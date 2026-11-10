"""Tools the LangGraph supervisor can call to dispatch work to agents."""
import os
import json
import subprocess
import uuid
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


def discover_agents() -> List[Dict[str, Any]]:
    """Auto-detect available agents from config and PATH."""
    agents_cfg = load_yaml(os.path.join(CONFIG_DIR, "agents.yaml"))
    agents = agents_cfg.get("agents", [])
    # Also check which CLIs are actually available on PATH
    import shutil
    available = {}
    for a in agents:
        cli = a.get("cli", "")
        available[a["id"]] = {
            "cli_found": shutil.which(cli) is not None,
            **a,
        }
    return list(available.values())


def discover_skills() -> List[Dict[str, Any]]:
    """Load skills from skills.yaml."""
    skills_cfg = load_yaml(os.path.join(CONFIG_DIR, "skills.yaml"))
    return skills_cfg.get("skills", [])


def discover_lanes() -> List[Dict[str, Any]]:
    """Load dispatch lanes from lanes.yaml."""
    lanes_cfg = load_yaml(os.path.join(CONFIG_DIR, "lanes.yaml"))
    return lanes_cfg.get("lanes", [])


def discover_projects() -> List[Dict[str, Any]]:
    """Load projects from projects.yaml."""
    projects_cfg = load_yaml(os.path.join(CONFIG_DIR, "projects.yaml"))
    return projects_cfg.get("projects", [])


def discover_models() -> List[Dict[str, Any]]:
    """Load models from models.yaml."""
    models_cfg = load_yaml(os.path.join(CONFIG_DIR, "models.yaml"))
    return models_cfg.get("models", [])


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
        "output_path": f"~/.agent-router/cards/{uuid.uuid4().hex[:8]}.md",
        "acceptance_check": acceptance,
        "budget": "10 minutes / 20 tool calls",
        "report": "<=15 lines: done / evidence (N of M) / blocked / next",
    }
    return packet


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
