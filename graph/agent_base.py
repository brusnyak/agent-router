"""Agent abstraction layer — every agent implements dispatch(packet) -> result."""
from __future__ import annotations

import os
import json
import shutil
import subprocess
import abc
from typing import Dict, Any, Optional, List
from pathlib import Path

HOME = os.path.expanduser("~")


class Agent(abc.ABC):
    """Base class for all agent types."""

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        self.id = agent_id
        self.config = config
        self.cli = config.get("cli", agent_id)
        self.model = config.get("model", "unknown")
        self.provider = config.get("provider", "cli")
        self.write_access = config.get("write_access", False)
        self.route_reasons = config.get("route_reasons", [])
        self.skills = config.get("skills", [])
        self.note = config.get("note", "")

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if this agent can be dispatched right now."""

    @abc.abstractmethod
    def dispatch(self, packet: Dict[str, Any]) -> str:
        """Dispatch a packet to this agent. Return the raw output string."""

    def build_launch_command(self, packet: Dict[str, Any]) -> str:
        """Build the shell command to launch this agent."""
        launch_cmd = self.config.get("launch_cmd", "")
        if not launch_cmd:
            return f"{self.cli} '{json.dumps(packet)}' </dev/null"

        dir_path = packet.get("project_context", {}).get("path", "~")
        mode = "workspace-write" if self.write_access else "read-only"
        return launch_cmd.format(
            packet=json.dumps(packet),
            dir=dir_path,
            mode=mode,
        )


class CLIAgent(Agent):
    """Agent launched via CLI subprocess (claude, codex, opencode, etc.)."""

    def is_available(self) -> bool:
        return shutil.which(self.cli) is not None

    def dispatch(self, packet: Dict[str, Any]) -> str:
        cmd = self.build_launch_command(packet)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.stdout or result.stderr or "No output"
        except subprocess.TimeoutExpired:
            return f"Agent {self.id} timed out after 120 seconds"
        except Exception as e:
            return f"Error launching {self.id}: {e}"


class NIMAgent(Agent):
    """Agent backed by a direct NIM model call (bypasses OpenCode/Zed)."""

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        self.api_key_env = config.get("api_key_env", "NIM_3")
        self.base_url = config.get("base_url", "https://integrate.api.nvidia.com/v1")
        self.nim_call_path = os.path.join(HOME, "memory-vault", "scripts", "nim_call.py")
        self.venv_python = os.path.join(HOME, ".memory", "venv", "bin", "python")

    def is_available(self) -> bool:
        api_key = os.environ.get(self.api_key_env, "")
        return bool(api_key) and os.path.exists(self.nim_call_path)

    def dispatch(self, packet: Dict[str, Any]) -> str:
        model = self.config.get("model", "nemotron-3.5-super-vl-120b-a12b")
        api_key = os.environ.get(self.api_key_env, "")
        if not api_key:
            return f"NIM agent {self.id}: {self.api_key_env} not set in environment"

        cmd = (
            f"{self.venv_python} {self.nim_call_path} "
            f"nim:{model} '{json.dumps(packet)}' </dev/null"
        )
        env = os.environ.copy()
        env[self.api_key_env] = api_key
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            return result.stdout or result.stderr or "No output"
        except subprocess.TimeoutExpired:
            return f"NIM agent {self.id} timed out after 120 seconds"
        except Exception as e:
            return f"Error calling NIM agent {self.id}: {e}"


class OrcaAgent(CLIAgent):
    """Agent launched via Orca's `orca agent launch`."""

    def dispatch(self, packet: Dict[str, Any]) -> str:
        cmd = self.build_launch_command(packet)
        # Orca agent launch may need the packet as a prompt argument
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.stdout or result.stderr or "No output"
        except subprocess.TimeoutExpired:
            return f"Orca agent {self.id} timed out after 120 seconds"
        except Exception as e:
            return f"Error launching Orca agent {self.id}: {e}"


# Registry of agent classes by provider type
AGENT_CLASSES = {
    "cli": CLIAgent,
    "nim": NIMAgent,
    "orca": OrcaAgent,
}


def create_agent(agent_id: str, config: Dict[str, Any]) -> Agent:
    """Factory: create an Agent instance from config."""
    provider = config.get("provider", "cli")
    cls = AGENT_CLASSES.get(provider, CLIAgent)
    return cls(agent_id, config)


def load_agent_config(agent_id: str) -> Optional[Dict[str, Any]]:
    """Load a single agent's config from agents.yaml."""
    import yaml
    config_dir = os.path.join(HOME, "Developer", "agent-router", "config")
    path = os.path.join(config_dir, "agents.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    for a in cfg.get("agents", []):
        if a.get("id") == agent_id:
            return a
    return None
