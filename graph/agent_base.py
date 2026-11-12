"""Agent abstraction layer — Phase 2: shell=False, git worktree isolation, vault sandbox.

Every agent implements dispatch(packet) -> result.
- shell=False: subprocess called with a list of args (no shell injection surface)
- Worktree isolation: each task runs in its own git worktree (or temp dir if no git)
- Vault sandbox: writes to ~/memory-vault/agents/<agent-id>/ only
- Packet passed via stdin (temp file), never interpolated into command strings
"""
from __future__ import annotations

import os
import sys
import json
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, List
import abc

HOME = os.path.expanduser("~")
ENV_FILE = os.path.join(HOME, ".env")
VAULT_SANDBOX = os.path.join(HOME, "memory-vault", "agents")


def _load_env() -> None:
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except OSError:
        pass


_load_env()


def _is_git_repo(path: str) -> bool:
    return Path(path, ".git").exists() or bool(
        subprocess.run(["git", "-C", path, "rev-parse", "--is-inside-work-tree"],
                       capture_output=True).returncode == 0
    )


def _create_worktree(project_path: str, task_id: str) -> Optional[str]:
    """Create a git worktree for task isolation. Returns worktree path or None."""
    if not project_path or not _is_git_repo(project_path):
        return None
    wt = os.path.join("/tmp", "agent-router-worktrees", task_id)
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "worktree", "add", "--detach", wt],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return wt
        # worktree may already exist; try to use it
        if os.path.isdir(wt):
            return wt
        return None
    except Exception:
        return None


def _cleanup_worktree(worktree_path: Optional[str], project_path: Optional[str]) -> None:
    if not worktree_path or not project_path:
        return
    try:
        subprocess.run(
            ["git", "-C", project_path, "worktree", "remove", "--force", worktree_path],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def _write_packet_file(packet: Dict[str, Any]) -> str:
    """Write packet to a temp file (never interpolate into shell). Returns path."""
    fd, path = tempfile.mkstemp(prefix="agent-router-packet-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(packet, f, indent=2)
    return path


def _vault_write_allowed(agent_id: str, target_path: str) -> bool:
    """Vault sandbox: agent may only write under ~/memory-vault/agents/<agent-id>/."""
    sandbox = os.path.join(VAULT_SANDBOX, agent_id)
    target = os.path.realpath(target_path)
    sandbox_real = os.path.realpath(sandbox)
    return target.startswith(sandbox_real + os.sep) or target == sandbox_real


class Agent(abc.ABC):
    # ------------------------------------------------------------------
    # Capability declaration
    # ------------------------------------------------------------------
    # Base capabilities all agents have. Subclasses override as needed.
    # `file-write` is only added by CLIAgent when write_access is True.
    CAPABILITIES: set[str] = {"text-generation"}

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
        self.interactive_mode = config.get("interactive_mode", False)

    def can(self, capability: str) -> bool:
        """Check if this agent has a given capability."""
        return capability in self.CAPABILITIES

    def can_write(self) -> bool:
        """Check if this agent can write files (capability + write_access config)."""
        return "file-write" in self.CAPABILITIES and self.write_access

    def claimed_files(self, output: str) -> list[str]:
        """Extract file paths the agent claims to have created/modified.

        Handles dotted paths (src/utils/helper.py) by allowing dots in the
        path character class. Stops at whitespace, quotes, commas, parens.
        """
        import re
        # Character class allows dots, slashes, underscores, hyphens, alphanumerics
        # Stops at whitespace, quotes, commas, closing parens
        path_char = r"[A-Za-z0-9_./\-~]+"
        patterns = [
            rf"Created\s+({path_char})",
            rf"wrote\s+to\s+({path_char})",
            rf"wrote\s+({path_char})",
            rf"saved\s+to\s+({path_char})",
            rf"at\s+({path_char})",
            rf"file[:\s]+({path_char})",
        ]
        found: set[str] = set()
        for pat in patterns:
            for m in re.finditer(pat, output, re.IGNORECASE):
                path = m.group(1).strip().rstrip(".,\"')")
                # Filter out common non-file words
                if path and not path.startswith(("http", "www")):
                    if path.lower() not in ("a", "the", "code", "output", "file", "script", "it", "this", "that"):
                        found.add(path)
        return sorted(found)

    @abc.abstractmethod
    def is_available(self) -> bool:
        ...

    @abc.abstractmethod
    def dispatch(self, packet: Dict[str, Any]) -> str:
        ...


class CLIAgent(Agent):
    """Agent launched via CLI subprocess — shell=False, worktree isolation."""

    CAPABILITIES = {"text-generation", "shell-access", "file-write"}
    INTERACTIVE_CLIS = {"claude", "codex", "opencode", "cline", "kilo", "hermes"}

    def is_available(self) -> bool:
        return shutil.which(self.cli) is not None

    def dispatch(self, packet: Dict[str, Any]) -> str:
        # Unattended safety: interactive CLIs (claude, codex, opencode, etc.) enter
        # a TUI and hang without a TTY. In unattended mode (interactive_mode=False),
        # refuse to dispatch them and route to NIM instead.
        if not self.interactive_mode and self.cli in self.INTERACTIVE_CLIS:
            return (f"Error: agent {self.id} ({self.cli}) is interactive and "
                    f"interactive_mode is disabled. Use a NIM agent or enable "
                    f"interactive_mode for attended sessions only.")

        project_path = packet.get("project_context", {}).get("path", "~")
        project_path = os.path.expanduser(project_path) if project_path else os.path.expanduser("~")

        worktree = _create_worktree(project_path, packet.get("task_id", str(uuid.uuid4())[:8]))
        cwd = worktree or project_path

        packet_json = json.dumps(packet, indent=2)

        # Build args as a list — shell=False.
        # The launch_cmd template has {packet}, {dir}, {mode}, {task_id} placeholders.
        # {packet} is replaced with the full JSON (kept as ONE argv element to preserve spaces).
        mode = "workspace-write" if self.write_access else "read-only"
        task_id = packet.get("task_id", str(uuid.uuid4())[:8])
        launch_cmd = self.config.get("launch_cmd", "")
        if launch_cmd:
            cmd_str = launch_cmd.format(
                packet="__PACKET_JSON__",
                dir=shlex.quote(cwd),
                mode=mode,
                task_id=task_id,
            )
            parts = shlex.split(cmd_str)
            args = [packet_json if p == "__PACKET_JSON__" else p for p in parts]
        else:
            args = [self.cli, packet_json]

        # Interactive CLI agents (claude, codex, opencode, etc.) need a TTY.
        # Wrap in `script` (macOS pseudo-terminal) while keeping shell=False.
        if self.cli in self.INTERACTIVE_CLIS and shutil.which("script"):
            args = ["script", "-q", "/dev/null"] + args

        env = os.environ.copy()
        try:
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=cwd,
                env=env,
                input=packet_json,
            )
            out = result.stdout or result.stderr or "No output"
            if result.returncode != 0:
                raise RuntimeError(f"Agent {self.id} exit code {result.returncode}: {out}")
            return out
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Agent {self.id} timed out after 300 seconds")
        except Exception as e:
            raise RuntimeError(f"Error launching {self.id}: {e}")
        finally:
            _cleanup_worktree(worktree, project_path)


class NIMAgent(Agent):
    """Agent backed by a direct NIM model call — shell=False, stdin packet."""

    CAPABILITIES = {"text-generation"}

    def __init__(self, agent_id: str, config: Dict[str, Any]):
        super().__init__(agent_id, config)
        self.api_key_env = config.get("api_key_env", "NIM_3")
        self.base_url = config.get("base_url", "https://integrate.api.nvidia.com/v1")
        _scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
        self.nim_call_path = os.path.abspath(os.path.join(_scripts_dir, "nim_call.py"))
        self.venv_python = os.path.join(os.path.expanduser("~"), ".memory", "venv", "bin", "python")

    def is_available(self) -> bool:
        api_key = os.environ.get(self.api_key_env, "")
        return bool(api_key) and os.path.exists(self.nim_call_path)

    def dispatch(self, packet: Dict[str, Any]) -> str:
        model = self.config.get("model", "nemotron-3.5-super-vl-120b-a12b")
        # Call OmniRoute gateway (http://localhost:20128/v1) — OmniRoute owns
        # NIM key rotation across nim1/nim2/nim3, fallback, and quota.
        # Errors are raised (not returned as strings) so callers can
        # distinguish success from failure via typed results.
        import urllib.request, urllib.error
        body = {
            "model": model,
            "messages": [{"role": "user", "content": packet.get("user_input", json.dumps(packet))}],
            "temperature": 0.2,
            "max_tokens": 4096,
        }
        if "nemotron" in model:
            body["chat_template_kwargs"] = {"enable_thinking": False}
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=data,
            headers={"Authorization": f"Bearer {os.environ.get(self.api_key_env, '')}",
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp_data = json.loads(resp.read().decode())
            content = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            if not content.strip():
                raise RuntimeError(f"NIM agent {self.id}: empty completion")
            return content
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            raise RuntimeError(f"NIM agent {self.id}: http {e.code} {detail}")
        except Exception as e:
            raise RuntimeError(f"NIM agent {self.id}: {e}")


class OrcaAgent(CLIAgent):
    """Agent launched via Orca's `orca agent launch`."""

    def dispatch(self, packet: Dict[str, Any]) -> str:
        # Reuse CLIAgent shell=False dispatch
        return super().dispatch(packet)


AGENT_CLASSES = {
    "cli": CLIAgent,
    "nim": NIMAgent,
    "orca": OrcaAgent,
}


def create_agent(agent_id: str, config: Dict[str, Any]) -> Agent:
    provider = config.get("provider", "cli")
    cls = AGENT_CLASSES.get(provider, CLIAgent)
    return cls(agent_id, config)


def load_agent_config(agent_id: str) -> Optional[Dict[str, Any]]:
    import yaml
    _agent_base_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = os.path.join(_agent_base_dir, "..", "config")
    path = os.path.abspath(os.path.join(config_dir, "agents.yaml"))
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    for a in cfg.get("agents", []):
        if a.get("id") == agent_id:
            return a
    return None


def vault_write_allowed(agent_id: str, target_path: str) -> bool:
    """Public: check if agent may write to target_path under vault sandbox."""
    return _vault_write_allowed(agent_id, target_path)
