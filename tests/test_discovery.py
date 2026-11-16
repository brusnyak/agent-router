"""Tests for machine discovery script."""
import json
import os
import sys
import tempfile
from pathlib import Path

HOME = os.path.expanduser("~")
PROJECT_ROOT = os.path.join(HOME, "Developer", "agent-router")
sys.path.insert(0, PROJECT_ROOT)

from scripts.discover_machine import discover, scan_cli_on_path, scan_agent_configs, scan_env_keys, scan_browsers, scan_vault, scan_skills, scan_hooks


def test_discover_returns_inventory():
    """discover() returns a dict with expected top-level keys."""
    inv = discover()
    assert "version" in inv
    assert "machine" in inv
    assert "agents" in inv
    assert "keys" in inv
    assert "browsers" in inv
    assert "vault" in inv
    assert "skills" in inv
    assert "hooks" in inv
    assert "project_roots" in inv
    assert "last30days" in inv
    assert "derived" in inv


def test_discover_writes_inventory_file():
    """discover() + main() writes config/discovered-inventory.json."""
    from scripts.discover_machine import main
    INVENTORY_PATH = os.path.join(PROJECT_ROOT, "config", "discovered-inventory.json")
    # Remove existing to test fresh write
    if os.path.exists(INVENTORY_PATH):
        os.remove(INVENTORY_PATH)
    main()
    assert os.path.exists(INVENTORY_PATH)
    with open(INVENTORY_PATH) as f:
        inv = json.load(f)
    assert "derived" in inv
    assert "usable_agents" in inv["derived"]


def test_scan_cli_on_path_returns_dict():
    """scan_cli_on_path() returns a dict with agent IDs as keys."""
    result = scan_cli_on_path()
    assert isinstance(result, dict)
    for aid in ("claude", "codex", "opencode", "cline", "kilo", "hermes"):
        assert aid in result
        assert isinstance(result[aid], bool)


def test_scan_agent_configs_returns_dict():
    """scan_agent_configs() returns config info per agent."""
    result = scan_agent_configs()
    assert isinstance(result, dict)
    for aid in ("claude", "codex"):
        assert aid in result
        assert "exists" in result[aid]
        assert "config_home" in result[aid]


def test_scan_env_keys_returns_dict():
    """scan_env_keys() returns dict of key presence."""
    result = scan_env_keys()
    assert isinstance(result, dict)
    for k in ("NIM_1", "NIM_2", "NIM_3", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        assert k in result
        assert isinstance(result[k], bool)


def test_scan_browsers_returns_list():
    """scan_browsers() returns a list of browser dicts."""
    result = scan_browsers()
    assert isinstance(result, list)
    for b in result:
        assert "id" in b
        assert "display_name" in b
        assert "installed" in b
        assert "running" in b
        assert "launch_cmd" in b


def test_scan_vault_returns_dict():
    """scan_vault() returns vault info dict."""
    result = scan_vault()
    assert isinstance(result, dict)
    assert "path" in result
    assert "exists" in result
    assert "agents_sandbox" in result


def test_scan_skills_returns_dict():
    """scan_skills() returns dict keyed by location."""
    result = scan_skills()
    assert isinstance(result, dict)
    total = 0
    for loc, data in result.items():
        assert "exists" in data
        assert "skill_files" in data
        total += len(data.get("skill_files", []))
    assert total > 0  # We know there are skills on this machine


def test_scan_hooks_returns_dict():
    """scan_hooks() returns hook info dict."""
    result = scan_hooks()
    assert isinstance(result, dict)
    assert "path" in result
    assert "exists" in result
    assert "hook_files" in result


def test_derived_usable_agents():
    """derived.usable_agents contains agents with CLI + config."""
    inv = discover()
    usable = inv["derived"]["usable_agents"]
    assert isinstance(usable, list)
    # claude and codex are known to be installed + configured
    assert "claude" in usable
    assert "codex" in usable


def test_browsers_available():
    """derived.browsers_available lists installed browsers."""
    inv = discover()
    browsers = inv["derived"]["browsers_available"]
    assert isinstance(browsers, list)
    assert "browserclaw" in browsers or "ego-lite" in browsers
    assert "ego-lite" in browsers or len(browsers) == 0


def test_vault_sandbox_ready():
    """derived.vault_sandbox_ready is True when vault exists."""
    inv = discover()
    assert inv["derived"]["vault_sandbox_ready"] is True


if __name__ == "__main__":
    test_discover_returns_inventory()
    test_discover_writes_inventory_file()
    test_scan_cli_on_path_returns_dict()
    test_scan_agent_configs_returns_dict()
    test_scan_env_keys_returns_dict()
    test_scan_browsers_returns_list()
    test_scan_vault_returns_dict()
    test_scan_skills_returns_dict()
    test_scan_hooks_returns_dict()
    test_derived_usable_agents()
    test_browsers_available()
    test_vault_sandbox_ready()
    print("All discovery tests passed.")
