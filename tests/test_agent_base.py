"""Tests for agent_base (shell=False, worktree isolation, vault sandbox, interactive mode)."""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
sys.path.insert(0, PROJECT_ROOT)

from graph.agent_base import (
    CLIAgent, NIMAgent, create_agent, load_agent_config,
    _vault_write_allowed, _create_worktree, _write_packet_file,
    VAULT_SANDBOX,
)


def test_vault_write_allowed_sandbox():
    """_vault_write_allowed() only permits writes under ~/memory-vault/agents/<agent-id>/."""
    sandbox = os.path.join(VAULT_SANDBOX, "nim3")
    os.makedirs(sandbox, exist_ok=True)

    # Allowed: under agent's sandbox
    allowed = _vault_write_allowed("nim3", os.path.join(sandbox, "note.md"))
    assert allowed is True

    # Allowed: the sandbox dir itself
    assert _vault_write_allowed("nim3", sandbox) is True

    # Blocked: outside sandbox
    assert _vault_write_allowed("nim3", os.path.join(HOME, "memory-vault", "pages", "secret.md")) is False
    assert _vault_write_allowed("nim3", "/tmp/evil.md") is False
    assert _vault_write_allowed("nim3", os.path.join(HOME, ".ssh", "id_rsa")) is False


def test_vault_write_allowed_different_agents():
    """Agent A cannot write to Agent B's sandbox."""
    sandbox_a = os.path.join(VAULT_SANDBOX, "agent-a")
    sandbox_b = os.path.join(VAULT_SANDBOX, "agent-b")
    os.makedirs(sandbox_a, exist_ok=True)
    os.makedirs(sandbox_b, exist_ok=True)

    assert _vault_write_allowed("agent-a", os.path.join(sandbox_b, "file.md")) is False
    assert _vault_write_allowed("agent-b", os.path.join(sandbox_a, "file.md")) is False


def test_cliagent_interactive_mode_blocks_unattended():
    """CLIAgent with interactive_mode=False refuses to dispatch interactive CLIs."""
    config = {
        "id": "claude",
        "cli": "claude",
        "model": "claude-default",
        "provider": "claude",
        "write_access": True,
        "interactive_mode": False,  # unattended
    }
    agent = CLIAgent("claude", config)
    result = agent.dispatch({"goal": "test", "task_id": "t1", "lane": "build"})
    assert "Error" in result
    assert "interactive_mode" in result


def test_cliagent_interactive_mode_allows_attended():
    """CLIAgent with interactive_mode=True does not return the interactive_mode error."""
    from unittest.mock import patch
    config = {
        "id": "claude",
        "cli": "claude",
        "model": "claude-default",
        "provider": "claude",
        "write_access": True,
        "interactive_mode": True,  # attended
    }
    agent = CLIAgent("claude", config)
    # Mock subprocess.run to avoid actually launching claude (would hang in TUI)
    with patch("graph.agent_base.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="mock output", stderr="", returncode=0)
        result = agent.dispatch({"goal": "test", "task_id": "t1", "lane": "build"})
    assert "interactive_mode" not in result  # not blocked by mode
    assert "mock output" in result


def test_nim_agent_dispatch_without_key():
    """NIMAgent.dispatch() returns error when API key missing."""
    config = {
        "id": "nim3",
        "cli": "nim_call.py",
        "model": "nvidia/nemotron-3.5-super-vl-120b-a12b",
        "provider": "nim",
        "api_key_env": "NIM_NONEXISTENT",
    }
    agent = NIMAgent("nim3", config)
    assert agent.is_available() is False  # no key + no nim_call.py path check
    result = agent.dispatch({"goal": "test", "task_id": "t1", "lane": "research"})
    assert "not set" in result or "Error" in result


def test_create_agent_factory():
    """create_agent() returns the right agent class."""
    cli_cfg = {"id": "codex", "cli": "codex", "model": "codex-default", "provider": "cli"}
    a = create_agent("codex", cli_cfg)
    assert isinstance(a, CLIAgent)

    nim_cfg = {"id": "nim3", "cli": "nim_call.py", "model": "m", "provider": "nim", "api_key_env": "NIM_3"}
    a = create_agent("nim3", nim_cfg)
    assert isinstance(a, NIMAgent)


def test_write_packet_file_creates_valid_json():
    """_write_packet_file() writes valid JSON to a temp file."""
    packet = {"goal": "test", "lane": "build"}
    path = _write_packet_file(packet)
    assert os.path.exists(path)
    with open(path) as f:
        loaded = json.load(f)
    assert loaded == packet
    os.unlink(path)


if __name__ == "__main__":
    test_vault_write_allowed_sandbox()
    test_vault_write_allowed_different_agents()
    test_cliagent_interactive_mode_blocks_unattended()
    test_cliagent_interactive_mode_allows_attended()
    test_nim_agent_dispatch_without_key()
    test_create_agent_factory()
    test_write_packet_file_creates_valid_json()
    print("All agent_base tests passed.")
